"""Adapters for group database classes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Tuple, cast

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.base_api.pagination import PaginationRequest
from renku_data_services.group import apispec, models
from renku_data_services.group import orm as schemas
from renku_data_services.users import orm as user_schemas


class GroupRepository:
    """Repository for groups."""

    def __init__(self, session_maker: Callable[..., AsyncSession], group_authz=None):
        self.session_maker = session_maker  # type: ignore[call-overload]
        self.group_authz: None | Any = group_authz

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
        stmt = select(schemas.GroupORM).where(schemas.GroupORM.slug == slug)
        if load_members:
            stmt = stmt.options(selectinload(schemas.GroupORM.members))
        if not session.in_transaction():
            async with session.begin():
                result = await session.execute(stmt)
        else:
            result = await session.execute(stmt)
        group_orm = result.scalar_one_or_none()
        if not group_orm:
            raise errors.MissingResourceError(message=f"The group with slug {slug} does not exist")
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
                .where(schemas.GroupMemberORM.group.has(schemas.GroupORM.slug == slug))
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
                        group.slug = v
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
                new_member_orm = schemas.GroupMemberORM(
                    user_id=new_member.id,
                    role=models.GroupRole.from_str(new_member.role.value).value,
                    group_id=group.id,
                )
                group.members[new_member.id] = new_member_orm
                output.append(new_member_orm.dump())
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
            stmt = delete(schemas.GroupORM).where(schemas.GroupORM.slug == slug)
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
            user_id = cast(str, user.id)
            member = schemas.GroupMemberORM(user.id, models.GroupRole.owner.value)
            session.add(member)
            group = schemas.GroupORM(
                name=payload.name,
                slug=payload.slug,
                description=payload.description,
                created_by=user_id,
                creation_date=creation_date,
                members={user_id: member},
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
