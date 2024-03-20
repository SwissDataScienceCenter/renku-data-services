"""Adapters for group database classes."""

from __future__ import annotations

import logging
import random
import re
import string
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Tuple, cast

from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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
            used_slugs = set()
            count = 0
            for user in res.scalars():
                slug = ""
                if user.email:
                    slug = user.email.split("@")[0]
                elif user.first_name and user.last_name:
                    slug = user.first_name + "-" + user.last_name
                elif user.last_name:
                    slug = user.last_name
                elif user.first_name:
                    slug = user.first_name
                else:
                    slug = "user_" + user.keycloak_id
                    logging.warn(
                        f"Could not find email, first name or last name for user"
                        f" with Keycloak ID {user.keycloak_id}, using slug {slug} based on Keycloak ID"
                    )
                if len(slug) > 80:
                    # The length limit is 99 but leave some space for some modifications we add down the line
                    # to filter out invalid characters or to generate a unique name
                    slug = slug[:80]
                if slug.startswith(("-", "_", ".")):
                    slug = "user" + slug
                # Replace any non-allowed characters
                slug = re.sub(r"[^a-zA-Z0-9-_.]", "-", slug)
                # Replace consecutive special characters
                slug = re.sub(r"[-_.]{2,}", "-", slug)
                # Check the new slug has not been used already
                if slug in used_slugs:
                    sep = "-"
                    if slug.endswith((".", "_", "-")):
                        sep = ""
                    logging.warn(
                        f"Slug {slug} for user with Keycloak ID {user.keycloak_id} "
                        "is already used, adding a count at the end to make unique"
                    )
                    for inc in range(1, 11):
                        new_slug = f"{slug}{sep}{inc}"
                        if new_slug not in used_slugs:
                            slug = new_slug
                            break
                    if slug in used_slugs:
                        logging.warn(
                            f"Cannot generate a new slug by counting, for slug {slug} will append a small random string"
                        )
                        slug += sep + "".join([random.choice(string.ascii_letters) for _ in range(6)])  # nosec: B311
                # Insert namespace in the db
                ns = schemas.NamespaceORM(slug=slug, user_id=user.keycloak_id)
                session.add(ns)
                used_slugs.add(slug)
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
        stmt = (
            select(schemas.NamespaceORM, schemas.GroupORM)
            .join(
                schemas.GroupORM,
                or_(
                    schemas.GroupORM.ltst_ns_slug_id == schemas.NamespaceORM.id,
                    schemas.GroupORM.ltst_ns_slug_id == schemas.NamespaceORM.ltst_ns_slug_id,
                ),
            )
            .where(func.lower(schemas.NamespaceORM.slug) == func.lower(slug))
        )
        if load_members:
            stmt = stmt.options(selectinload(schemas.GroupORM.members))
        if not session.in_transaction():
            async with session.begin():
                result = await session.execute(stmt)
        else:
            result = await session.execute(stmt)
        row = result.one_or_none()
        if not row:
            raise errors.MissingResourceError(message=f"The group with slug {slug} does not exist")
        _, group_orm = row.tuple()
        return group_orm

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
                raise errors.Unauthorized(message="Only the owner and admins can modify groups")
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
            for k, v in payload.items():
                match k:
                    case "slug":
                        new_slug_str = v.lower()
                        if new_slug_str == slug.lower():
                            # The slug has not changed at all
                            break
                        new_slug_exists = (
                            await session.execute(
                                select(schemas.NamespaceORM).where(schemas.NamespaceORM.slug == new_slug_str)
                            )
                        ).scalar_one_or_none()
                        if new_slug_exists and not new_slug_exists.ltst_ns_slug:
                            # The slug exists in the database and it is marked as the latest/current slug
                            # for a group or a user namespace
                            raise errors.ValidationError(
                                message=f"The slug {v} is already in use, please try a different one"
                            )
                        old_slug_str = group.ltst_ns_slug.slug.lower()
                        if new_slug_exists and new_slug_exists.ltst_ns_slug:
                            # NOTE: The new slug exists from another project or user, but this slug has already
                            # been replaced in this other project by a newer slug so this means we can reclaim the
                            # the slug from the other group or user to use it in this group
                            new_slug_exists.ltst_ns_slug = None
                            # Make sure the slug does not point to another user
                            new_slug_exists.user_id = None
                            new_slug_exists.user = None
                            # Assign the slug to the requested group
                            group.ltst_ns_slug = new_slug_exists
                        else:
                            # The slug is brand new so we replace the value of the latest slug with it
                            # and then make a new version of the old slug that points to the latest version
                            group.ltst_ns_slug.slug = new_slug_str
                        old_slug = schemas.NamespaceORM(slug=old_slug_str, ltst_ns_slug=group.ltst_ns_slug)
                        session.add(old_slug)
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
            stmt = delete(schemas.GroupORM).where(schemas.GroupORM.id == group.id)
            await session.execute(stmt)

    async def delete_group_member(self, user: base_models.APIUser, slug: str, user_id_to_delete: str):
        """Delete a specific group member."""
        async with self.session_maker() as session, session.begin():
            group = await self._get_group(session, slug)
            if user.id != group.created_by and not user.is_admin:
                raise errors.Unauthorized(message="Only the owner and admins can modify groups")
            stmt = delete(schemas.GroupMemberORM).where(schemas.GroupMemberORM.user_id == user_id_to_delete)
            await session.execute(stmt)

    async def insert_group(self, user: base_models.APIUser, payload: apispec.GroupPostRequest) -> models.Group:
        """Insert a new group."""
        async with self.session_maker() as session, session.begin():
            if not user.id:
                raise errors.Unauthorized(message="Users need to be authenticated in order to create groups.")
            creation_date = datetime.now(timezone.utc).replace(microsecond=0)
            member = schemas.GroupMemberORM(user.id, models.GroupRole.owner.value)
            ns = schemas.NamespaceORM(slug=payload.slug.lower())
            session.add(ns)
            group = schemas.GroupORM(
                name=payload.name,
                description=payload.description,
                created_by=user.id,
                creation_date=creation_date,
                members={user.id: member},
                ltst_ns_slug=ns,
            )

            session.add(group)
            try:
                await session.flush()
            except IntegrityError as err:
                if len(err.args) > 0 and "UniqueViolationError" in err.args[0] and "slug" in err.args[0]:
                    raise errors.ValidationError(
                        message="The slug for the group should be unique but it already exists in the database",
                        detail="Please modify the slug field and then retry",
                    )
            return group.dump()

    async def get_namespaces(
        self, user: base_models.APIUser, pagination: PaginationRequest
    ) -> Tuple[List[models.Namespace], int]:
        """Get all namespaces."""
        async with self.session_maker() as session, session.begin():
            group_nss_stmt = (
                select(schemas.NamespaceORM, schemas.GroupORM)
                .join(
                    schemas.GroupORM,
                    or_(
                        schemas.GroupORM.ltst_ns_slug_id == schemas.NamespaceORM.id,
                        schemas.GroupORM.ltst_ns_slug_id == schemas.NamespaceORM.ltst_ns_slug_id,
                    ),
                )
                .where(schemas.GroupORM.members.any(schemas.GroupMemberORM.user_id == user.id))
            )
            output = []
            if pagination.page == 1:
                personal_ns_stmt = select(schemas.NamespaceORM).where(schemas.NamespaceORM.user_id == user.id)
                personal_ns = (await session.execute(personal_ns_stmt)).scalar_one_or_none()
                if personal_ns:
                    output.append(personal_ns.dump())
            # NOTE: in the first page the personal namespace is added, so the offset and per page params are modified
            group_per_page = pagination.per_page - len(output) if pagination.page == 1 else pagination.per_page
            group_offset = 0 if pagination.page == 1 else pagination.offset - len(output)
            group_nss = (await session.execute(group_nss_stmt.limit(group_per_page).offset(group_offset))).tuples()
            group_count = (
                await session.execute(group_nss_stmt.with_only_columns(func.count(schemas.NamespaceORM.id)))
            ).scalar() or 0
            group_count += len(output)
            for ns_orm, _ in group_nss:
                output.append(ns_orm.dump())
            return output, group_count

    async def get_ns_group_orm(
        self, user: base_models.APIUser, slug: str
    ) -> Tuple[schemas.NamespaceORM | None, schemas.GroupORM | None]:
        """Get the namespace and group ORM for a slug."""
        async with self.session_maker() as session, session.begin():
            stmt = (
                select(schemas.NamespaceORM, schemas.GroupORM)
                .join(
                    schemas.GroupORM,
                    or_(
                        schemas.GroupORM.ltst_ns_slug_id == schemas.NamespaceORM.id,
                        schemas.GroupORM.ltst_ns_slug_id == schemas.NamespaceORM.ltst_ns_slug_id,
                    ),
                    isouter=True,  # NOTE: if ommitted it will only return groups, without user namespaces
                )
                .where(
                    or_(
                        schemas.GroupORM.members.any(schemas.GroupMemberORM.user_id == user.id),
                        schemas.NamespaceORM.user_id == user.id,
                    )
                )
                .where(func.lower(schemas.NamespaceORM.slug) == func.lower(slug))
            )
            nss = (await session.execute(stmt)).all()
            if len(nss) != 1:
                return None, None
            return nss[0].tuple()

    async def get_namespace(self, user: base_models.APIUser, slug: str) -> models.Namespace | None:
        """Get the namespace for a slug."""
        ns, grp = await self.get_ns_group_orm(user, slug)
        if not ns:
            return None
        ns_dump = ns.dump()
        if grp:
            ns_dump.name = grp.name
            ns_dump.created_by = grp.created_by
            ns_dump.creation_date = grp.creation_date
        elif ns.user:
            if ns.user.first_name or ns.user.last_name:
                if ns.user.first_name:
                    ns_dump.name = ns.user.first_name
                if ns.user.last_name and not ns_dump.name:
                    ns_dump.name = ns.user.last_name
                elif ns.user.last_name and ns_dump.name:
                    ns_dump.name += f" {ns.user.last_name}"
            ns_dump.created_by = ns.user_id
        return ns_dump
