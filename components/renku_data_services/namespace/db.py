"""Adapters for group database classes."""

from __future__ import annotations

import random
import string
from collections.abc import AsyncGenerator, Callable
from contextlib import nullcontext
from datetime import UTC, datetime

from sanic.log import logger
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.authz.authz import Authz, AuthzOperation, ResourceType
from renku_data_services.authz.models import Member, MembershipChange, Role, Scope
from renku_data_services.base_api.pagination import PaginationRequest
from renku_data_services.message_queue import events
from renku_data_services.message_queue.avro_models.io.renku.events.v2 import GroupAdded, GroupRemoved, GroupUpdated
from renku_data_services.message_queue.db import EventRepository
from renku_data_services.message_queue.interface import IMessageQueue
from renku_data_services.message_queue.redis_queue import dispatch_message
from renku_data_services.namespace import apispec, models
from renku_data_services.namespace import orm as schemas
from renku_data_services.users import models as user_models
from renku_data_services.users import orm as user_schemas
from renku_data_services.utils.core import with_db_transaction


class GroupRepository:
    """Repository for groups."""

    def __init__(
        self,
        session_maker: Callable[..., AsyncSession],
        event_repo: EventRepository,
        group_authz: Authz,
        message_queue: IMessageQueue,
    ) -> None:
        self.session_maker = session_maker
        self.authz: Authz = group_authz
        self.event_repo: EventRepository = event_repo
        self.message_queue: IMessageQueue = message_queue

    @with_db_transaction
    @Authz.authz_change(AuthzOperation.insert_many, ResourceType.user_namespace)
    @dispatch_message(events.InsertUserNamespace)
    async def generate_user_namespaces(
        self, *, session: AsyncSession | None = None
    ) -> list[user_models.UserWithNamespace]:
        """Generate user namespaces if the user table has data and the namespaces table is empty."""
        if not session:
            raise errors.ProgrammingError(message="A database session is required")
        # NOTE: lock to make sure another instance of the data service cannot insert/update but can read
        output: list[user_models.UserWithNamespace] = []
        await session.execute(text("LOCK TABLE common.namespaces IN EXCLUSIVE MODE"))
        at_least_one_namespace = (await session.execute(select(schemas.NamespaceORM).limit(1))).one_or_none()
        if at_least_one_namespace:
            logger.info("Found at least one user namespace, skipping creation")
            return output
        logger.info("Found zero user namespaces, will try to create them from users table")
        res = await session.scalars(select(user_schemas.UserORM))
        for user in res:
            ns = await self._insert_user_namespace(session, user, retry_enumerate=10, retry_random=True)
            logger.info(f"Creating user namespace {ns}")
            output.append(user_models.UserWithNamespace(user.dump(), ns))
        logger.info(f"Created {len(output)} user namespaces")
        return output

    async def get_groups(
        self,
        user: base_models.APIUser,
        pagination: PaginationRequest,
    ) -> tuple[list[models.Group], int]:
        """Get all groups from the database."""
        async with self.session_maker() as session, session.begin():
            stmt = select(schemas.GroupORM).limit(pagination.per_page).offset(pagination.offset)
            stmt = stmt.order_by(schemas.GroupORM.creation_date.asc(), schemas.GroupORM.id.asc(), schemas.GroupORM.name)
            result = await session.execute(stmt)
            groups_orm = result.scalars().all()

            stmt_count = select(func.count()).select_from(schemas.GroupORM)
            result = await session.execute(stmt_count)
            n_total_elements = result.scalar() or 0
            return [g.dump() for g in groups_orm], n_total_elements

    async def _get_group(
        self, session: AsyncSession, user: base_models.APIUser, slug: str, load_members: bool = False
    ) -> tuple[schemas.GroupORM, list[Member]]:
        transaction = nullcontext() if session.in_transaction() else session.begin()
        async with transaction:  # type: ignore[attr-defined]
            stmt = select(schemas.GroupORM).where(
                schemas.GroupORM.namespace.has(schemas.NamespaceORM.slug == slug.lower())
            )
            group = await session.scalar(stmt)
            if not group:
                stmt_old_ns = (
                    select(schemas.NamespaceOldORM)
                    .where(schemas.NamespaceOldORM.slug == slug.lower())
                    .order_by(schemas.NamespaceOldORM.created_at.desc())
                    .limit(1)
                    .options(
                        joinedload(schemas.NamespaceOldORM.latest_slug)
                        .joinedload(schemas.NamespaceORM.group)
                        .joinedload(schemas.GroupORM.namespace)
                    )
                )
                old_ns = await session.scalar(stmt_old_ns)
                if old_ns is not None and old_ns.latest_slug.group is not None:
                    group = old_ns.latest_slug.group
            if not group:
                raise errors.MissingResourceError(message=f"The group with slug {slug} does not exist")
            members = []
            if load_members:
                members = await self.authz.members(user, ResourceType.group, group.id)
            return group, members

    async def get_group(self, user: base_models.APIUser, slug: str) -> models.Group:
        """Get a group from the DB."""
        async with self.session_maker() as session:
            group_orm, _ = await self._get_group(session, user, slug)
        return group_orm.dump()

    @with_db_transaction
    async def get_group_members(
        self, user: base_models.APIUser, slug: str, *, session: AsyncSession | None = None
    ) -> list[models.GroupMemberDetails]:
        """Get all the users that are direct members of a group."""
        if not session:
            raise errors.ProgrammingError(message="A database session is required")
        _, members = await self._get_group(session, user, slug, load_members=True)
        members_dict = {i.user_id: i for i in members}
        stmt = select(user_schemas.UserORM).where(user_schemas.UserORM.keycloak_id.in_(members_dict.keys()))
        result = await session.scalars(stmt)
        return [
            models.GroupMemberDetails(
                id=member.keycloak_id,
                role=members_dict[member.keycloak_id].role,
                email=member.email,
                first_name=member.first_name,
                last_name=member.last_name,
            )
            for member in result
        ]

    @with_db_transaction
    @dispatch_message(GroupUpdated)
    async def update_group(
        self, user: base_models.APIUser, slug: str, payload: dict[str, str], *, session: AsyncSession | None = None
    ) -> models.Group:
        """Update a group in the DB."""
        if not session:
            raise errors.ProgrammingError(message="A database session is required")
        group, _ = await self._get_group(session, user, slug)
        if user.id != group.created_by and not user.is_admin:
            raise errors.Unauthorized(message="Only the owner and admins can modify groups")
        if group.namespace.slug != slug.lower():
            raise errors.UpdatingWithStaleContentError(
                message=f"You cannot update a group by using its old slug {slug}.",
                detail=f"The latest slug is {group.namespace.slug}, please use this for updates.",
            )
        for k, v in payload.items():
            match k:
                case "slug":
                    new_slug_str = v.lower()
                    if group.namespace.slug == new_slug_str:
                        # The slug has not changed at all.
                        # NOTE that the continue will work only because of the enclosing loop over the payload
                        continue
                    new_slug_already_taken = await session.scalar(
                        select(schemas.NamespaceORM).where(schemas.NamespaceORM.slug == new_slug_str)
                    )
                    if new_slug_already_taken:
                        raise errors.ValidationError(
                            message=f"The slug {v} is already in use, please try a different one"
                        )
                    session.add(schemas.NamespaceOldORM(slug=group.namespace.slug, latest_slug_id=group.namespace.id))
                    group.namespace.slug = new_slug_str
                case "description":
                    group.description = v
                case "name":
                    group.name = v
        return group.dump()

    @with_db_transaction
    @dispatch_message(events.GroupMembershipChanged)
    async def update_group_members(
        self,
        user: base_models.APIUser,
        slug: str,
        payload: apispec.GroupMemberPatchRequestList,
        *,
        session: AsyncSession | None = None,
    ) -> list[MembershipChange]:
        """Update group members."""
        if not session:
            raise errors.ProgrammingError(message="A database session is required")
        group, existing_members = await self._get_group(session, user, slug, load_members=True)
        if group.namespace.slug != slug.lower():
            raise errors.UpdatingWithStaleContentError(
                message=f"You cannot update group members by using an old group slug {slug}.",
                detail=f"The latest slug is {group.namespace.slug}, please use this for updates.",
            )
        members = [Member(Role.from_group_role(member.role), member.id, group.id) for member in payload.root]
        output = await self.authz.upsert_group_members(user, ResourceType.group, group.id, members)
        return output

    @with_db_transaction
    @Authz.authz_change(AuthzOperation.delete, ResourceType.group)
    @dispatch_message(GroupRemoved)
    async def delete_group(
        self, user: base_models.APIUser, slug: str, *, session: AsyncSession | None = None
    ) -> models.Group | None:
        """Delete a specific group."""
        if not session:
            raise errors.ProgrammingError(message="A database session is required")
        group: None | schemas.GroupORM = None
        try:
            group, _ = await self._get_group(session, user, slug)
        except errors.MissingResourceError:
            return None
        if group.namespace.slug != slug.lower():
            raise errors.UpdatingWithStaleContentError(
                message=f"You cannot delete a group by using an old group slug {slug}.",
                detail=f"The latest slug is {group.namespace.slug}, please use this for deletions.",
            )
        # NOTE: We have a stored procedure that gets triggered when a project slug is removed to remove the project.
        # This is required because the slug has a foreign key pointing to the project, so when a project is removed
        # the slug is removed but the converse is not true. The stored procedure in migration 89aa4573cfa9 has the
        # trigger and procedure that does the cleanup when a slug is removed.
        stmt = delete(schemas.GroupORM).where(schemas.GroupORM.id == group.id)
        await session.execute(stmt)
        return group.dump()

    @with_db_transaction
    @dispatch_message(events.GroupMembershipChanged)
    async def delete_group_member(
        self, user: base_models.APIUser, slug: str, user_id_to_delete: str, *, session: AsyncSession | None = None
    ) -> list[MembershipChange]:
        """Delete a specific group member."""
        if not session:
            raise errors.ProgrammingError(message="A database session is required")
        if not user.id:
            raise errors.Unauthorized(message="Users need to be authenticated in order to remove group members.")
        group, _ = await self._get_group(session, user, slug)
        output = await self.authz.remove_group_members(user, ResourceType.group, group.id, [user_id_to_delete])
        return output

    @with_db_transaction
    @Authz.authz_change(AuthzOperation.create, ResourceType.group)
    @dispatch_message(GroupAdded)
    async def insert_group(
        self,
        user: base_models.APIUser,
        payload: apispec.GroupPostRequest,
        *,
        session: AsyncSession | None = None,
    ) -> models.Group:
        """Insert a new group."""
        if not session:
            raise errors.ProgrammingError(message="A database session is required")
        if not user.id:
            raise errors.Unauthorized(message="Users need to be authenticated in order to create groups.")
        creation_date = datetime.now(UTC).replace(microsecond=0)
        group = schemas.GroupORM(
            name=payload.name,
            description=payload.description,
            created_by=user.id,
            creation_date=creation_date,
        )
        session.add(group)
        ns = schemas.NamespaceORM(slug=payload.slug.lower(), group_id=group.id)
        session.add(ns)
        try:
            await session.flush()
        except IntegrityError as err:
            if len(err.args) > 0 and "UniqueViolationError" in err.args[0] and "slug" in err.args[0]:
                raise errors.ValidationError(
                    message="The slug for the group should be unique but it already exists in the database",
                    detail="Please modify the slug field and then retry",
                )
            raise err
        # NOTE: This is needed to populate the relationship fields in the group after inserting the ID above
        await session.refresh(group)
        return group.dump()

    async def get_namespaces(
        self, user: base_models.APIUser, pagination: PaginationRequest
    ) -> tuple[list[models.Namespace], int]:
        """Get all namespaces."""
        async with self.session_maker() as session, session.begin():
            group_ids = await self.authz.resources_with_permission(user, user.id, ResourceType.group, Scope.READ)
            group_ns_stmt = select(schemas.NamespaceORM).where(schemas.NamespaceORM.group_id.in_(group_ids))
            output = []
            if pagination.page == 1:
                personal_ns_stmt = select(schemas.NamespaceORM).where(schemas.NamespaceORM.user_id == user.id)
                personal_ns = await session.scalar(personal_ns_stmt)
                if personal_ns:
                    output.append(personal_ns.dump())
            # NOTE: in the first page the personal namespace is added, so the offset and per page params are modified
            group_per_page = pagination.per_page - len(output) if pagination.page == 1 else pagination.per_page
            group_offset = 0 if pagination.page == 1 else pagination.offset - len(output)
            group_ns = await session.scalars(
                group_ns_stmt.limit(group_per_page).offset(group_offset).order_by(schemas.NamespaceORM.id)
            )
            group_count = (
                await session.scalar(group_ns_stmt.with_only_columns(func.count(schemas.NamespaceORM.id))) or 0
            )
            group_count += len(output)
            for ns_orm in group_ns:
                output.append(ns_orm.dump())
            return output, group_count

    async def _get_user_namespaces(self) -> AsyncGenerator[user_models.UserWithNamespace, None]:
        """Lists all user namespaces without regard for authorization or permissions, used for migrations."""
        async with self.session_maker() as session, session.begin():
            namespaces = await session.stream_scalars(
                select(schemas.NamespaceORM).where(schemas.NamespaceORM.user_id.isnot(None))
            )
            async for namespace in namespaces:
                yield namespace.dump_user()

    async def get_namespace_by_slug(self, user: base_models.APIUser, slug: str) -> models.Namespace | None:
        """Get the namespace identified by a given slug."""
        async with self.session_maker() as session, session.begin():
            ns = await session.scalar(select(schemas.NamespaceORM).where(schemas.NamespaceORM.slug == slug.lower()))
            old_ns = None
            if not ns:
                old_ns = await session.scalar(
                    select(schemas.NamespaceOldORM)
                    .where(schemas.NamespaceOldORM.slug == slug.lower())
                    .order_by(schemas.NamespaceOldORM.created_at.desc())
                    .limit(1)
                )
                if not old_ns:
                    return None
                ns = old_ns.latest_slug
            if ns.group and ns.group_id:
                is_allowed = await self.authz.has_permission(user, ResourceType.group, ns.group_id, Scope.READ)
                if not is_allowed:
                    raise errors.MissingResourceError(
                        message=f"The group with slug {slug} does not exist or you do not have permissions to view it"
                    )
                return ns.dump()
            if not ns.user or not ns.user_id:
                raise errors.ProgrammingError(message="Found a namespace that has no group or user associated with it.")
            is_allowed = await self.authz.has_permission(user, ResourceType.user_namespace, ns.id, Scope.READ)
            if not is_allowed:
                raise errors.MissingResourceError(
                    message=f"The namespace with slug {slug} does not exist or you do not have permissions to view it"
                )
            return ns.dump()

    async def get_user_namespace(self, user_id: str) -> models.Namespace | None:
        """Get the namespace corresponding to a given user."""
        async with self.session_maker() as session, session.begin():
            ns = await session.scalar(select(schemas.NamespaceORM).where(schemas.NamespaceORM.user_id == user_id))
            if ns is None:
                return None
            if not ns.user or not ns.user_id:
                raise errors.ProgrammingError(message="Found a namespace that has no user associated with it.")
            return ns.dump()

    async def _insert_user_namespace(
        self, session: AsyncSession, user: schemas.UserORM, retry_enumerate: int = 0, retry_random: bool = False
    ) -> models.Namespace:
        """Insert a new namespace for the user and optionally retry different variations to avoid collisions."""
        original_slug = user.to_slug()
        for inc in range(0, retry_enumerate + 1):
            # NOTE: on iteration 0 we try with the optimal slug value derived from the user data without any suffix.
            suffix = ""
            if inc > 0:
                suffix = f"-{inc}"
            slug = base_models.Slug.from_name(original_slug.value.lower() + suffix)
            ns = schemas.NamespaceORM(slug.value, user_id=user.keycloak_id)
            try:
                async with session.begin_nested():
                    session.add(ns)
                    await session.flush()
            except IntegrityError:
                if retry_enumerate == 0:
                    raise errors.ValidationError(message=f"The user namespace slug {slug.value} already exists")
                continue
            else:
                await session.refresh(ns)
                return ns.dump()
        if not retry_random:
            raise errors.ValidationError(
                message=f"Cannot create generate a unique namespace slug for the user with ID {user.keycloak_id}"
            )
        # NOTE: At this point the attempts to generate unique ID have ended and the only option is
        # to add a small random suffix to avoid uniqueness constraints problems
        suffix = "-" + "".join([random.choice(string.ascii_lowercase + string.digits) for _ in range(8)])  # nosec: B311
        slug = base_models.Slug.from_name(original_slug.value.lower() + suffix)
        ns = schemas.NamespaceORM(slug.value, user_id=user.keycloak_id)
        session.add(ns)
        await session.flush()
        await session.refresh(ns)
        return ns.dump()
