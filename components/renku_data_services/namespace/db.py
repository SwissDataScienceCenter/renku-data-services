"""Adapters for group database classes."""

from __future__ import annotations

import random
import string
from collections.abc import AsyncGenerator, Callable
from contextlib import nullcontext
from datetime import UTC, datetime
from typing import Any

from sanic.log import logger
from sqlalchemy import Select, delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.authz.authz import Authz, AuthzOperation, ResourceType
from renku_data_services.authz.models import CheckPermissionItem, Member, MembershipChange, Role, Scope, UnsavedMember
from renku_data_services.base_api.pagination import PaginationRequest, paginate_queries
from renku_data_services.base_models.core import Slug
from renku_data_services.message_queue import events
from renku_data_services.message_queue.avro_models.io.renku.events.v2 import GroupAdded, GroupRemoved, GroupUpdated
from renku_data_services.message_queue.db import EventRepository
from renku_data_services.message_queue.interface import IMessageQueue
from renku_data_services.message_queue.redis_queue import dispatch_message
from renku_data_services.namespace import models
from renku_data_services.namespace import orm as schemas
from renku_data_services.project.orm import ProjectORM
from renku_data_services.search.db import SearchUpdatesRepo
from renku_data_services.search.decorators import update_search_document
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
        search_updates_repo: SearchUpdatesRepo,
    ) -> None:
        self.session_maker = session_maker
        self.authz: Authz = group_authz
        self.event_repo: EventRepository = event_repo
        self.message_queue: IMessageQueue = message_queue
        self.search_updates_repo = search_updates_repo

    @with_db_transaction
    @Authz.authz_change(AuthzOperation.insert_many, ResourceType.user_namespace)
    @dispatch_message(events.InsertUserNamespace)
    @update_search_document
    async def generate_user_namespaces(self, *, session: AsyncSession | None = None) -> list[user_models.UserInfo]:
        """Generate user namespaces if the user table has data and the namespaces table is empty."""
        if not session:
            raise errors.ProgrammingError(message="A database session is required")
        # NOTE: lock to make sure another instance of the data service cannot insert/update but can read
        output: list[user_models.UserInfo] = []
        await session.execute(text("LOCK TABLE common.namespaces IN EXCLUSIVE MODE"))
        at_least_one_namespace = (await session.execute(select(schemas.NamespaceORM).limit(1))).one_or_none()
        if at_least_one_namespace:
            logger.info("Found at least one user namespace, skipping creation")
            return []
        logger.info("Found zero user namespaces, will try to create them from users table")
        res = await session.scalars(select(user_schemas.UserORM))
        for user in res:
            slug = base_models.Slug.from_user(user.email, user.first_name, user.last_name, user.keycloak_id)
            ns = await self._insert_user_namespace(
                session, user.keycloak_id, slug.value, retry_enumerate=10, retry_random=True
            )
            logger.info(f"Creating user namespace {ns}")
            user.namespace = ns
            output.append(user.dump())
        logger.info(f"Created {len(output)} user namespaces")
        return output

    async def get_groups(
        self, user: base_models.APIUser, pagination: PaginationRequest, direct_member: bool = False
    ) -> tuple[list[models.Group], int]:
        """Get all groups from the database."""
        if direct_member:
            group_ids = await self.authz.resources_with_direct_membership(user, ResourceType.group)

        async with self.session_maker() as session, session.begin():
            stmt = select(schemas.GroupORM)
            if direct_member:
                stmt = stmt.where(schemas.GroupORM.id.in_(group_ids))
            stmt = stmt.limit(pagination.per_page).offset(pagination.offset)
            stmt = stmt.order_by(schemas.GroupORM.id.desc())
            result = await session.execute(stmt)
            groups_orm = result.scalars().all()

            stmt_count = select(func.count()).select_from(schemas.GroupORM)
            if direct_member:
                stmt_count = stmt_count.where(schemas.GroupORM.id.in_(group_ids))
            result = await session.execute(stmt_count)
            n_total_elements = result.scalar() or 0
            return [g.dump() for g in groups_orm], n_total_elements

    async def get_all_groups(self, requested_by: base_models.APIUser) -> AsyncGenerator[models.Group, None]:
        """Get all groups when reprovisioning."""
        if not requested_by.is_admin:
            raise errors.ForbiddenError(message="You do not have the required permissions for this operation.")

        async with self.session_maker() as session:
            groups = await session.stream_scalars(select(schemas.GroupORM))
            async for group in groups:
                yield group.dump()

    async def _get_group(
        self, session: AsyncSession, user: base_models.APIUser, slug: Slug, load_members: bool = False
    ) -> tuple[schemas.GroupORM, list[Member]]:
        transaction = nullcontext() if session.in_transaction() else session.begin()
        async with transaction:
            stmt = select(schemas.GroupORM).where(
                schemas.GroupORM.namespace.has(schemas.NamespaceORM.slug == slug.value.lower())
            )
            group = await session.scalar(stmt)
            if not group:
                stmt_old_ns = (
                    select(schemas.NamespaceOldORM)
                    .where(schemas.NamespaceOldORM.slug == slug.value.lower())
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

    async def get_group(self, user: base_models.APIUser, slug: Slug) -> models.Group:
        """Get a group from the DB."""
        async with self.session_maker() as session:
            group_orm, _ = await self._get_group(session, user, slug)
        return group_orm.dump()

    @with_db_transaction
    async def get_group_members(
        self, user: base_models.APIUser, slug: Slug, *, session: AsyncSession | None = None
    ) -> list[models.GroupMemberDetails]:
        """Get all the users that are direct members of a group."""
        if not session:
            raise errors.ProgrammingError(message="A database session is required")
        _, members = await self._get_group(session, user, slug, load_members=True)
        members_dict = {i.user_id: i for i in members}
        stmt = select(user_schemas.UserORM).where(user_schemas.UserORM.keycloak_id.in_(members_dict.keys()))
        result = await session.scalars(stmt)

        namespaces_stmt = select(schemas.NamespaceORM).where(schemas.NamespaceORM.user_id.in_(members_dict.keys()))
        namespaces_result = await session.scalars(namespaces_stmt)
        namespaces_dict = {ns.user_id: ns for ns in namespaces_result}

        return [
            models.GroupMemberDetails(
                id=member.keycloak_id,
                role=members_dict[member.keycloak_id].role,
                first_name=member.first_name,
                last_name=member.last_name,
                namespace=namespaces_dict[member.keycloak_id].slug,
            )
            for member in result
        ]

    @with_db_transaction
    @dispatch_message(GroupUpdated)
    @update_search_document
    async def update_group(
        self, user: base_models.APIUser, slug: Slug, patch: models.GroupPatch, *, session: AsyncSession | None = None
    ) -> models.Group:
        """Update a group in the DB."""
        if not session:
            raise errors.ProgrammingError(message="A database session is required")
        group, _ = await self._get_group(session, user, slug)
        if group.namespace.slug != slug.value.lower():
            raise errors.UpdatingWithStaleContentError(
                message=f"You cannot update a group by using its old slug {slug.value}.",
                detail=f"The latest slug is {group.namespace.slug}, please use this for updates.",
            )

        authorized = await self.authz.has_permission(user, ResourceType.group, group.id, Scope.DELETE)
        if not authorized:
            raise errors.MissingResourceError(
                message=f"Group with slug '{slug.value}' does not exist or you do not have access to it."
            )

        new_slug_str = patch.slug.lower() if patch.slug is not None else None
        if new_slug_str is not None and new_slug_str != group.namespace.slug:
            # Only update if the slug has changed.
            new_slug_already_taken = await session.scalar(
                select(schemas.NamespaceORM).where(schemas.NamespaceORM.slug == new_slug_str)
            )
            if new_slug_already_taken:
                raise errors.ValidationError(
                    message=f"The slug {new_slug_str} is already in use, please try a different one"
                )
            session.add(schemas.NamespaceOldORM(slug=group.namespace.slug, latest_slug_id=group.namespace.id))
            group.namespace.slug = new_slug_str
        if patch.name is not None:
            group.name = patch.name
        if patch.description is not None:
            group.description = patch.description if patch.description else None

        return group.dump()

    @with_db_transaction
    @dispatch_message(events.GroupMembershipChanged)
    async def update_group_members(
        self,
        user: base_models.APIUser,
        slug: Slug,
        members: list[UnsavedMember],
        *,
        session: AsyncSession | None = None,
    ) -> list[MembershipChange]:
        """Update group members."""
        if not session:
            raise errors.ProgrammingError(message="A database session is required")
        group, _ = await self._get_group(session, user, slug, load_members=True)
        if group.namespace.slug != slug.value.lower():
            raise errors.UpdatingWithStaleContentError(
                message=f"You cannot update group members by using an old group slug {slug.value}.",
                detail=f"The latest slug is {group.namespace.slug}, please use this for updates.",
            )

        output = await self.authz.upsert_group_members(
            user, ResourceType.group, group.id, [m.with_group(group.id) for m in members]
        )
        return output

    @with_db_transaction
    @Authz.authz_change(AuthzOperation.delete, ResourceType.group)
    @dispatch_message(GroupRemoved)
    @update_search_document
    async def delete_group(
        self, user: base_models.APIUser, slug: Slug, *, session: AsyncSession | None = None
    ) -> models.DeletedGroup | None:
        """Delete a specific group."""
        if not session:
            raise errors.ProgrammingError(message="A database session is required")
        group: None | schemas.GroupORM = None
        try:
            group, _ = await self._get_group(session, user, slug)
        except errors.MissingResourceError:
            return None
        if group.namespace.slug != slug.value.lower():
            raise errors.UpdatingWithStaleContentError(
                message=f"You cannot delete a group by using an old group slug {slug.value}.",
                detail=f"The latest slug is {group.namespace.slug}, please use this for deletions.",
            )
        # NOTE: We have a stored procedure that gets triggered when a project slug is removed to remove the project.
        # This is required because the slug has a foreign key pointing to the project, so when a project is removed
        # the slug is removed but the converse is not true. The stored procedure in migration 89aa4573cfa9 has the
        # trigger and procedure that does the cleanup when a slug is removed.
        stmt = delete(schemas.GroupORM).where(schemas.GroupORM.id == group.id)
        await session.execute(stmt)
        return models.DeletedGroup(id=group.id)

    @with_db_transaction
    @dispatch_message(events.GroupMembershipChanged)
    async def delete_group_member(
        self, user: base_models.APIUser, slug: Slug, user_id_to_delete: str, *, session: AsyncSession | None = None
    ) -> list[MembershipChange]:
        """Delete a specific group member."""
        if not session:
            raise errors.ProgrammingError(message="A database session is required")
        if not user.id:
            raise errors.UnauthorizedError(message="Users need to be authenticated in order to remove group members.")
        group, _ = await self._get_group(session, user, slug)
        output = await self.authz.remove_group_members(user, ResourceType.group, group.id, [user_id_to_delete])
        return output

    @with_db_transaction
    @Authz.authz_change(AuthzOperation.create, ResourceType.group)
    @dispatch_message(GroupAdded)
    @update_search_document
    async def insert_group(
        self,
        user: base_models.APIUser,
        payload: models.UnsavedGroup,
        *,
        session: AsyncSession | None = None,
    ) -> models.Group:
        """Insert a new group."""
        if not session:
            raise errors.ProgrammingError(message="A database session is required")
        if not user.id:
            raise errors.UnauthorizedError(message="Users need to be authenticated in order to create groups.")
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

    async def get_group_permissions(self, user: base_models.APIUser, slug: Slug) -> models.GroupPermissions:
        """Get the permissions of the user on a given group."""
        group = await self.get_group(user=user, slug=slug)

        scopes = [Scope.WRITE, Scope.DELETE, Scope.CHANGE_MEMBERSHIP]
        items = [
            CheckPermissionItem(resource_type=ResourceType.group, resource_id=group.id, scope=scope) for scope in scopes
        ]
        responses = await self.authz.has_permissions(user=user, items=items)
        permissions = models.GroupPermissions(write=False, delete=False, change_membership=False)
        for item, has_permission in responses:
            if not has_permission:
                continue
            match item.scope:
                case Scope.WRITE:
                    permissions.write = True
                case Scope.DELETE:
                    permissions.delete = True
                case Scope.CHANGE_MEMBERSHIP:
                    permissions.change_membership = True
        return permissions

    async def get_namespaces(
        self,
        user: base_models.APIUser,
        pagination: PaginationRequest,
        minimum_role: Role | None = None,
        kinds: list[models.NamespaceKind] | None = None,
    ) -> tuple[list[models.Namespace], int]:
        """Get all namespaces."""
        scope = Scope.READ
        if minimum_role == Role.VIEWER:
            scope = Scope.READ_CHILDREN
        elif minimum_role == Role.EDITOR:
            scope = Scope.WRITE
        elif minimum_role == Role.OWNER:
            scope = Scope.DELETE

        async with self.session_maker() as session, session.begin():
            group_ids: list[str] = []
            project_ids: list[str] = []
            user_ids: list[str] = []
            if not kinds or models.NamespaceKind.group in kinds:
                group_ids = await self.authz.resources_with_permission(user, user.id, ResourceType.group, scope)
            if (not kinds or models.NamespaceKind.user in kinds) and user.id:
                user_ids.append(user.id)
            if not kinds or models.NamespaceKind.project in kinds:
                project_ids = await self.authz.resources_with_permission(user, user.id, ResourceType.project, scope)

            queries: list[tuple[Select[tuple[Any]], int]] = [
                (
                    select(schemas.NamespaceORM)
                    .where(schemas.NamespaceORM.user_id.in_(user_ids))
                    .order_by(schemas.NamespaceORM.id),
                    len(user_ids),
                ),
                (
                    select(schemas.NamespaceORM)
                    .where(schemas.NamespaceORM.group_id.in_(group_ids))
                    .order_by(schemas.NamespaceORM.id),
                    len(group_ids),
                ),
                (select(ProjectORM).where(ProjectORM.id.in_(project_ids)).order_by(ProjectORM.id), len(project_ids)),
            ]

            results = await paginate_queries(pagination, session, queries)
            output: list[models.Namespace] = []
            for res in results:
                match res:
                    case schemas.NamespaceORM():
                        output.append(res.dump())
                    case ProjectORM():
                        output.append(res.dump_as_namespace())
                    case x:
                        raise errors.ProgrammingError(
                            message=f"Got an unexpected type of object when listing namespaces {type(x)}"
                        )
            return output, len(group_ids) + len(user_ids) + len(project_ids)

    async def _get_user_namespaces(self) -> AsyncGenerator[user_models.UserInfo, None]:
        """Lists all user namespaces without regard for authorization or permissions, used for migrations."""
        async with self.session_maker() as session, session.begin():
            namespaces = await session.stream_scalars(
                select(schemas.NamespaceORM).where(schemas.NamespaceORM.user_id.isnot(None))
            )
            async for namespace in namespaces:
                yield namespace.dump_user()

    async def get_namespace_by_slug(self, user: base_models.APIUser, slug: Slug) -> models.Namespace | None:
        """Get the namespace identified by a given slug."""
        async with self.session_maker() as session, session.begin():
            ns = await session.scalar(
                select(schemas.NamespaceORM).where(schemas.NamespaceORM.slug == slug.value.lower())
            )
            old_ns = None
            if not ns:
                old_ns = await session.scalar(
                    select(schemas.NamespaceOldORM)
                    .where(schemas.NamespaceOldORM.slug == slug.value.lower())
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

    async def get_user_namespace(self, user_id: str) -> models.UserNamespace | None:
        """Get the namespace corresponding to a given user."""
        async with self.session_maker() as session, session.begin():
            ns = await session.scalar(select(schemas.NamespaceORM).where(schemas.NamespaceORM.user_id == user_id))
            if ns is None:
                return None
            if not ns.user or not ns.user_id:
                raise errors.ProgrammingError(message="Found a namespace that has no user associated with it.")
            return ns.dump_user_namespace()

    async def _create_user_namespace_slug(
        self, session: AsyncSession, user_slug: str, retry_enumerate: int = 0, retry_random: bool = False
    ) -> str:
        """Create a valid namespace slug for a user."""
        nss = await session.scalars(
            select(schemas.NamespaceORM.slug).where(schemas.NamespaceORM.slug.startswith(user_slug))
        )
        nslist = nss.all()
        if user_slug not in nslist:
            return user_slug
        if retry_enumerate:
            for inc in range(1, retry_enumerate + 1):
                slug = f"{user_slug}-{inc}"
                if slug not in nslist:
                    return slug
        if retry_random:
            suffix = "".join([random.choice(string.ascii_lowercase + string.digits) for _ in range(8)])  # nosec B311
            slug = f"{user_slug}-{suffix}"
            if slug not in nslist:
                return slug

        raise errors.ValidationError(message=f"Cannot create generate a unique namespace slug for the user {user_slug}")

    async def _insert_user_namespace(
        self, session: AsyncSession, user_id: str, user_slug: str, retry_enumerate: int = 0, retry_random: bool = False
    ) -> schemas.NamespaceORM:
        """Insert a new namespace for the user and optionally retry different variations to avoid collisions."""
        namespace = await self._create_user_namespace_slug(session, user_slug, retry_enumerate, retry_random)
        slug = base_models.Slug.from_name(namespace)
        ns = schemas.NamespaceORM(slug.value, user_id=user_id)
        session.add(ns)
        await session.flush()
        await session.refresh(ns)
        return ns
