"""Adapters for group database classes."""

from __future__ import annotations

import logging
import random
import string
from contextlib import nullcontext
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Tuple, cast

from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.base_api.pagination import PaginationRequest
from renku_data_services.namespace import apispec, models
from renku_data_services.namespace import orm as schemas
from renku_data_services.users import orm as user_schemas


class GroupRepository:
    """Repository for groups."""

    def __init__(self, session_maker: Callable[..., AsyncSession], group_authz=None):
        self.session_maker = session_maker  # type: ignore[call-overload]
        self.group_authz: None | Any = group_authz

    async def generate_user_namespaces(self):
        """Generate user namespaces if the user table has data and the namespaces table is empty."""
        async with self.session_maker() as session, session.begin():
            # NOTE: lock to make sure another instance of the data service cannot insert/update but can read
            await session.execute(text("LOCK TABLE common.namespaces IN EXCLUSIVE MODE"))
            at_least_one_namespace = (await session.execute(select(schemas.NamespaceORM).limit(1))).one_or_none()
            if at_least_one_namespace:
                logging.info("Found at least one user namespace, skipping creation")
                return
            logging.info("Found zero user namespaces, will try to create them from users table")
            res = await session.execute(select(user_schemas.UserORM))
            count = 0
            for user in res.scalars():
                ns = await self.insert_user_namespace(user, session, retry_enumerate=10, retry_random=True)
                logging.info(f"Creating user namespace {ns}")
                count += 1
        logging.info(f"Created {count} user namespaces")

    async def get_groups(
        self,
        user: base_models.APIUser,
        pagination: PaginationRequest,
    ) -> Tuple[list[models.Group], int]:
        """Get all groups from the database."""
        async with self.session_maker() as session, session.begin():
            stmt = select(schemas.GroupORM).limit(pagination.per_page).offset(pagination.offset)
            stmt = stmt.order_by(schemas.GroupORM.creation_date.asc(), schemas.GroupORM.id.asc(), schemas.GroupORM.name)
            result = await session.execute(stmt)
            groups_orm = result.scalars().all()

            stmt_count = select(func.count()).select_from(schemas.GroupORM)
            result = await session.execute(stmt_count)
            n_total_elements = cast(int, result.scalar() or 0)
            return [g.dump() for g in groups_orm], n_total_elements

    async def _get_group(self, session: AsyncSession, slug: str, load_members: bool = False) -> schemas.GroupORM:
        transaction = nullcontext() if session.in_transaction() else session.begin()
        async with transaction:  # type: ignore[attr-defined]
            stmt = select(schemas.GroupORM).where(
                schemas.GroupORM.namespace.has(schemas.NamespaceORM.slug == slug.lower())
            )
            if load_members:
                stmt = stmt.options(joinedload(schemas.GroupORM.members))
            group = await session.scalar(stmt)
            if group:
                return group
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
            if load_members:
                stmt_old_ns = stmt_old_ns.options(
                    joinedload(schemas.NamespaceOldORM.latest_slug)
                    .joinedload(schemas.NamespaceORM.group)
                    .joinedload(schemas.GroupORM.members)
                )
            old_ns = await session.scalar(stmt_old_ns)
            if not old_ns or not old_ns.latest_slug.group:
                raise errors.MissingResourceError(message=f"The group with slug {slug} does not exist")
            return old_ns.latest_slug.group

    async def get_group(self, slug: str) -> models.Group:
        """Get a group from the DB."""
        async with self.session_maker() as session:
            group_orm = await self._get_group(session, slug)
        return group_orm.dump()

    async def get_group_members(self, user: base_models.APIUser, slug: str) -> List[models.GroupMemberDetails]:
        """Get all the users that are direct members of a group."""
        async with self.session_maker() as session, session.begin():
            group = await self._get_group(session, slug)
            if user.id != group.created_by and not user.is_admin:
                # TODO: implement a more fine-grained authorization scheme
                raise errors.Unauthorized(message="Only the owner and admins can list the members of a group")
            stmt = (
                select(schemas.GroupMemberORM, user_schemas.UserORM)
                .where(schemas.GroupMemberORM.group.has(schemas.GroupORM.id == group.id))
                .join(user_schemas.UserORM, schemas.GroupMemberORM.user_id == user_schemas.UserORM.keycloak_id)
            )
            result = await session.execute(stmt)
            return [
                models.GroupMemberDetails(
                    id=details.keycloak_id,
                    role=models.GroupRole(member.role),
                    email=details.email,
                    first_name=details.first_name,
                    last_name=details.last_name,
                )
                for member, details in result.all()
            ]

    async def update_group(self, user: base_models.APIUser, slug: str, payload: Dict[str, str]) -> models.Group:
        """Update a group in the DB."""
        async with self.session_maker() as session, session.begin():
            group = await self._get_group(session, slug)
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
                            # The slug has not changed at all
                            # NOTE that the continue will work only because of the enclosing loop over the payload
                            continue
                        new_slug_already_taken = await session.scalar(
                            select(schemas.NamespaceORM).where(schemas.NamespaceORM.slug == new_slug_str)
                        )
                        if new_slug_already_taken:
                            raise errors.ValidationError(
                                message=f"The slug {v} is already in use, please try a different one"
                            )
                        session.add(
                            schemas.NamespaceOldORM(slug=group.namespace.slug, latest_slug_id=group.namespace.id)
                        )
                        group.namespace.slug = new_slug_str
                    case "description":
                        group.description = v
                    case "name":
                        group.name = v
            return group.dump()

    async def update_group_members(
        self,
        user: base_models.APIUser,
        slug: str,
        payload: apispec.GroupMemberPatchRequestList,
    ) -> List[models.GroupMember]:
        """Update group members."""
        async with self.session_maker() as session, session.begin():
            group = await self._get_group(session, slug, True)
            if user.id != group.created_by and not user.is_admin:
                raise errors.Unauthorized(message="Only the owner and admins can modify groups")
            if group.namespace.slug != slug.lower():
                raise errors.UpdatingWithStaleContentError(
                    message=f"You cannot update group members by using an old group slug {slug}.",
                    detail=f"The latest slug is {group.namespace.slug}, please use this for updates.",
                )
            output = []
            for new_member in payload.root:
                role = models.GroupRole.from_str(new_member.role.value)
                if new_member.id in group.members:
                    # The member exists in the group already, check if properties should be updated
                    if group.members[new_member.id].role != role.value:
                        group.members[new_member.id].role = role.value
                    output.append(group.members[new_member.id].dump())
                else:
                    # The memeber does not exist in the group at all, make a new entry and add it to the group
                    member_orm = schemas.GroupMemberORM(user_id=new_member.id, role=role)
                    group.members[new_member.id] = member_orm
                    output.append(member_orm.dump())
            return output

    async def delete_group(self, user: base_models.APIUser, slug: str):
        """Delete a specific group."""
        async with self.session_maker() as session, session.begin():
            try:
                group = await self._get_group(session, slug)
            except errors.MissingResourceError:
                return
            if user.id != group.created_by and not user.is_admin:
                raise errors.Unauthorized(message="Only the owner and admins can modify groups")
            if group.namespace.slug != slug.lower():
                raise errors.UpdatingWithStaleContentError(
                    message=f"You cannot delete a group by using an old group slug {slug}.",
                    detail=f"The latest slug is {group.namespace.slug}, please use this for deletions.",
                )
            stmt = delete(schemas.GroupORM).where(schemas.GroupORM.id == group.id)
            await session.execute(stmt)

    async def delete_group_member(self, user: base_models.APIUser, slug: str, user_id_to_delete: str):
        """Delete a specific group member."""
        async with self.session_maker() as session, session.begin():
            group = await self._get_group(session, slug)
            if user.id != group.created_by and not user.is_admin:
                raise errors.Unauthorized(message="Only the owner and admins can modify groups")
            if group.namespace.slug != slug.lower():
                raise errors.UpdatingWithStaleContentError(
                    message=f"You cannot remove a group member by using an old group slug {slug}.",
                    detail=f"The latest slug is {group.namespace.slug}, please retry the request with it.",
                )
            stmt = delete(schemas.GroupMemberORM).where(schemas.GroupMemberORM.user_id == user_id_to_delete)
            await session.execute(stmt)

    async def insert_group(self, user: base_models.APIUser, payload: apispec.GroupPostRequest) -> models.Group:
        """Insert a new group."""
        async with self.session_maker() as session, session.begin():
            if not user.id:
                raise errors.Unauthorized(message="Users need to be authenticated in order to create groups.")
            creation_date = datetime.now(timezone.utc).replace(microsecond=0)
            member = schemas.GroupMemberORM(user.id, models.GroupRole.owner.value)
            group = schemas.GroupORM(
                name=payload.name,
                description=payload.description,
                created_by=user.id,
                creation_date=creation_date,
                members={user.id: member},
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
            # NOTE: This is needed to populate the relationship fields in the group after inserting the ID above
            await session.refresh(group)
            return group.dump()

    async def get_namespaces(
        self, user: base_models.APIUser, pagination: PaginationRequest
    ) -> Tuple[List[models.Namespace], int]:
        """Get all namespaces."""
        async with self.session_maker() as session, session.begin():
            group_ns_stmt = select(schemas.NamespaceORM).where(
                schemas.NamespaceORM.group.has(schemas.GroupORM.members.any(schemas.GroupMemberORM.user_id == user.id))
            )
            output = []
            if pagination.page == 1:
                personal_ns_stmt = select(schemas.NamespaceORM).where(schemas.NamespaceORM.user_id == user.id)
                personal_ns = await session.scalar(personal_ns_stmt)
                if personal_ns:
                    output.append(personal_ns.dump())
            # NOTE: in the first page the personal namespace is added, so the offset and per page params are modified
            group_per_page = pagination.per_page - len(output) if pagination.page == 1 else pagination.per_page
            group_offset = 0 if pagination.page == 1 else pagination.offset - len(output)
            group_ns = await session.scalars(group_ns_stmt.limit(group_per_page).offset(group_offset))
            group_count = (
                await session.scalar(group_ns_stmt.with_only_columns(func.count(schemas.NamespaceORM.id))) or 0
            )
            group_count += len(output)
            for ns_orm in group_ns:
                output.append(ns_orm.dump())
            return output, group_count

    async def get_namespace(self, user: base_models.APIUser, slug: str) -> models.Namespace | None:
        """Get the namespace for a slug."""
        async with self.session_maker() as session, session.begin():
            ns = await session.scalar(
                select(schemas.NamespaceORM)
                .where(schemas.NamespaceORM.slug == slug.lower())
                .where(
                    or_(
                        schemas.NamespaceORM.user_id == user.id,
                        schemas.NamespaceORM.group.has(
                            schemas.GroupORM.members.any(schemas.GroupMemberORM.user_id == user.id)
                        ),
                    )
                )
            )
            old_ns = None
            if not ns:
                old_ns = await session.scalar(
                    select(schemas.NamespaceOldORM)
                    .where(schemas.NamespaceOldORM.slug == slug.lower())
                    .where(
                        or_(
                            schemas.NamespaceOldORM.latest_slug.has(schemas.NamespaceORM.user_id == user.id),
                            schemas.NamespaceOldORM.latest_slug.has(
                                schemas.NamespaceORM.group.has(
                                    schemas.GroupORM.members.any(schemas.GroupMemberORM.user_id == user.id)
                                )
                            ),
                        )
                    )
                    .order_by(schemas.NamespaceOldORM.created_at.desc())
                    .limit(1)
                )
                if not old_ns:
                    return None
                ns = old_ns.latest_slug
            if ns.group:
                return models.Namespace(
                    id=ns.id,
                    name=ns.group.name,
                    created_by=ns.group.created_by,
                    creation_date=ns.group.creation_date,
                    kind=models.NamespaceKind.group,
                    slug=old_ns.slug if old_ns else ns.slug,
                    latest_slug=ns.slug,
                )
            if not ns.user:
                raise errors.ProgrammingError(message="Found a namespace that has no group or user associated with it.")
            name: str | None
            if ns.user.first_name and ns.user.last_name:
                name = f"{ns.user.first_name} {ns.user.last_name}"
            else:
                name = ns.user.first_name or ns.user.last_name
            return models.Namespace(
                id=ns.id,
                name=name,
                created_by=ns.user.keycloak_id,
                kind=models.NamespaceKind.user,
                slug=old_ns.slug if old_ns else ns.slug,
                latest_slug=ns.slug,
            )

    async def insert_user_namespace(
        self, user: schemas.UserORM, session: AsyncSession, retry_enumerate: int = 0, retry_random: bool = False
    ) -> schemas.NamespaceORM:
        """Insert a new namespace for the user and optionally retry different variatioins to avoid collisions."""
        # session.add(user)  # reattach the user to the session
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
            except IntegrityError:
                if retry_enumerate == 0:
                    raise errors.ValidationError(message=f"The user namespace slug {slug.value} already exists")
                continue
            else:
                return ns
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
        return ns
