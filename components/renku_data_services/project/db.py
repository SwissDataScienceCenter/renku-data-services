"""Adapters for project database classes."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, NamedTuple, Tuple, cast

from sanic.log import logger
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.authz import models as authz_models
from renku_data_services.authz.authz import IProjectAuthorizer
from renku_data_services.authz.models import MemberQualifier, Scope
from renku_data_services.project import apispec, models
from renku_data_services.message_queue.avro_models.io.renku.events.v1.visibility import Visibility as MsgVisibility
from renku_data_services.message_queue.db import EventRepository
from renku_data_services.message_queue.interface import IMessageQueue
from renku_data_services.project import models
from renku_data_services.project import orm as schemas
from renku_data_services.project.apispec import Role, Visibility


def convert_to_authz_role(role: Role) -> authz_models.Role:
    """Covert from project member Role to authz Role."""
    return authz_models.Role.OWNER if role == Role.owner else authz_models.Role.MEMBER


def convert_from_authz_role(role: authz_models.Role) -> Role:
    """Covert from authz Role to project member Role."""
    return Role.owner if authz_models.Role.OWNER == role else Role.member


class PaginationResponse(NamedTuple):
    """Paginated response."""

    page: int
    per_page: int
    total: int
    total_pages: int


class ProjectRepository:
    """Repository for project."""

    def __init__(
        self,
        session_maker: Callable[..., AsyncSession],
        project_authz: IProjectAuthorizer,
        message_queue: IMessageQueue,
        event_repo: EventRepository,
    ):
        self.session_maker = session_maker  # type: ignore[call-overload]
        self.project_authz: IProjectAuthorizer = project_authz
        self.message_queue: IMessageQueue = message_queue
        self.event_repo: EventRepository = event_repo

    async def get_projects(
        self, user: base_models.APIUser, page: int, per_page: int
    ) -> Tuple[list[models.Project], PaginationResponse]:
        """Get all projects from the database."""
        if page < 1:
            raise errors.ValidationError(message="Parameter 'page' must be a natural number")
        offset = (page - 1) * per_page
        if offset > 2**63 - 1:
            raise errors.ValidationError(message="Parameter 'page' is too large")
        if per_page < 1 or per_page > 100:
            raise errors.ValidationError(message="Parameter 'per_page' must be between 1 and 100")

        user_id = user.id if user.is_authenticated else MemberQualifier.ALL
        # NOTE: without the line below mypy thinks user_id can be None
        user_id = user_id if user_id is not None else MemberQualifier.ALL
        project_ids = await self.project_authz.get_user_projects(requested_by=user, user_id=user_id, scope=Scope.READ)

        async with self.session_maker() as session:
            stmt = select(schemas.ProjectORM)
            stmt = stmt.where(schemas.ProjectORM.id.in_(project_ids))
            stmt = stmt.limit(per_page).offset(offset)
            stmt = stmt.order_by(schemas.ProjectORM.creation_date.desc())
            result = await session.execute(stmt)
            projects_orm = result.scalars().all()

            stmt_count = select(func.count()).select_from(schemas.ProjectORM)
            result = await session.execute(stmt_count)
            n_total_elements = cast(int, result.scalar() or 0)
            total_pages, remainder = divmod(n_total_elements, per_page)
            if remainder:
                total_pages += 1

            pagination = PaginationResponse(page, per_page, n_total_elements, total_pages)

            return [p.dump() for p in projects_orm], pagination

    async def get_project(self, user: base_models.APIUser, project_id: str) -> models.Project:
        """Get one project from the database."""
        authorized = await self.project_authz.has_permission(user=user, project_id=project_id, scope=Scope.READ)
        if not authorized:
            raise errors.MissingResourceError(
                message=f"Project with id '{project_id}' does not exist or you do not have access to it."
            )

        async with self.session_maker() as session:
            stmt = select(schemas.ProjectORM).where(schemas.ProjectORM.id == project_id)
            result = await session.execute(stmt)
            project_orm = result.scalars().first()

            if project_orm is None:
                raise errors.MissingResourceError(message=f"Project with id '{project_id}' does not exist.")

            return project_orm.dump()

    async def insert_project(self, user: base_models.APIUser, new_project=apispec.ProjectPost) -> models.Project:
        """Insert a new project entry."""

        project_dict = new_project.model_dump(exclude_none=True)
        user_id: str = cast(str, user.id)
        project_dict["created_by"] = models.Member(id=user_id)
        project_model = models.Project.from_dict(project_dict)
        project = schemas.ProjectORM.load(project_model)

        async with self.session_maker() as session:
            async with session.begin():
                session.add(project)

                logger.info(f"orm creation_date = {project.creation_date}")
                logger.info(f"orm updated_at = {project.updated_at}")
                project_model = project.dump()
                logger.info(f"model creation_date = {project_model.creation_date}")
                logger.info(f"model updated_at = {project_model.updated_at}")
                public_project = project_model.visibility == Visibility.public
                if project_model.id is None:
                    raise errors.BaseError(detail="The created project does not have an ID but it should.")
                await self.project_authz.create_project(
                    requested_by=user, project_id=project_model.id, public_project=public_project
                )

                # Need to commit() to get the timestamps(?)
                await session.commit()
                logger.info(f"orm creation_date = {project.creation_date}")
                logger.info(f"orm updated_at = {project.updated_at}")
                return project.dump()

    async def update_project(
        self, user: base_models.APIUser, project_id: str, etag: str | None = None, **payload
    ) -> models.Project:
        """Update a project entry."""
        authorized = await self.project_authz.has_permission(user=user, project_id=project_id, scope=Scope.WRITE)
        if not authorized:
            raise errors.MissingResourceError(
                message=f"Project with id '{project_id}' does not exist or you do not have access to it."
            )

        async with self.session_maker() as session:
            async with session.begin():
                result = await session.scalars(select(schemas.ProjectORM).where(schemas.ProjectORM.id == project_id))
                project = result.one_or_none()

                if project is None:
                    raise errors.MissingResourceError(message=f"The project with id '{project_id}' cannot be found")

                current_etag = project.dump().etag
                if etag is not None and current_etag != etag:
                    raise errors.ConflictError(message=f"Current ETag is {current_etag}, not {etag}.")

                visibility_before = project.visibility
        match project.visibility:
            case Visibility.private | Visibility.private.value:
                vis = MsgVisibility.PRIVATE
            case Visibility.public | Visibility.public.value:
                vis = MsgVisibility.PUBLIC
            case _:
                raise NotImplementedError(f"unknown visibility:{project.visibility}")
        async with self.message_queue.project_updated_message(
            name=project.name,
            slug=project.slug,
            visibility=vis,
            id=project.id,
            repositories=[r.url for r in project.repositories],
            description=project.description,
        ) as message:
            async with self.session_maker() as session:
                async with session.begin():
                    session.add(project)  # reattach to session
                    if "repositories" in payload:
                        payload["repositories"] = [
                            schemas.ProjectRepositoryORM(url=r, project_id=project_id, project=project)
                            for r in payload["repositories"]
                        ]

                if "repositories" in payload:
                    payload["repositories"] = [
                        schemas.ProjectRepositoryORM(url=r, project_id=project_id, project=project)
                        for r in payload["repositories"]
                    ]
                    # Trigger update for ``updated_at`` column
                    await session.execute(
                        update(schemas.ProjectORM).where(schemas.ProjectORM.id == project_id).values()
                    )

                    if visibility_before != project.visibility:
                        public_project = project.visibility == Visibility.public
                        await self.project_authz.update_project_visibility(
                            requested_by=user, project_id=project_id, public_project=public_project
                        )
                    await message.persist(self.event_repo)

                    return project.dump()  # NOTE: Triggers validation before the transaction saves data

    async def delete_project(self, user: base_models.APIUser, project_id: str) -> None:
        """Delete a cloud project entry."""
        authorized = await self.project_authz.has_permission(user=user, project_id=project_id, scope=Scope.DELETE)
        if not authorized:
            raise errors.MissingResourceError(
                message=f"Project with id '{project_id}' does not exist or you do not have access to it."
            )

        async with self.message_queue.project_removed_message(
            id=project_id,
        ) as message:
            async with self.session_maker() as session:
                async with session.begin():
                    result = await session.execute(
                        select(schemas.ProjectORM).where(schemas.ProjectORM.id == project_id)
                    )
                    projects = result.one_or_none()

                    if projects is None:
                        return

                    await session.delete(projects[0])

                    await self.project_authz.delete_project(requested_by=user, project_id=project_id)
                    await message.persist(self.event_repo)


class ProjectMemberRepository:
    """Repository for project members."""

    def __init__(self, session_maker: Callable[..., AsyncSession], project_authz: IProjectAuthorizer):
        self.session_maker = session_maker  # type: ignore[call-overload]
        self.project_authz: IProjectAuthorizer = project_authz

    async def get_members(self, user: base_models.APIUser, project_id: str) -> List[models.MemberWithRole]:
        """Get all members of a project."""
        authorized = await self.project_authz.has_permission(user=user, project_id=project_id, scope=Scope.READ)
        if not authorized:
            raise errors.MissingResourceError(
                message=f"Project with id '{project_id}' does not exist or you do not have access to it."
            )

        members = await self.project_authz.get_project_users(requested_by=user, project_id=project_id, scope=Scope.READ)

        return [
            models.MemberWithRole(member=models.Member(id=m.user_id), role=convert_from_authz_role(m.role))
            for m in members
        ]

    async def update_members(self, user: base_models.APIUser, project_id: str, members: List[Dict[str, Any]]) -> None:
        """Update project's members."""
        authorized = await self.project_authz.has_permission(user=user, project_id=project_id, scope=Scope.WRITE)
        if not authorized:
            raise errors.MissingResourceError(
                message=f"Project with id '{project_id}' does not exist or you do not have access to it."
            )

        async with self.session_maker() as session:
            async with session.begin():
                result = await session.execute(select(schemas.ProjectORM).where(schemas.ProjectORM.id == project_id))
                project = result.one_or_none()
                if project is None:
                    raise errors.MissingResourceError(message=f"The project with id '{project_id}' cannot be found")

                for member in members:
                    await self.project_authz.update_or_add_user(
                        requested_by=user,
                        project_id=project_id,
                        user_id=member["member"]["id"],
                        role=convert_to_authz_role(Role(member["role"])),
                    )

    async def delete_member(self, user: base_models.APIUser, project_id: str, member_id: str) -> None:
        """Delete a single member from a project."""
        authorized = await self.project_authz.has_permission(user=user, project_id=project_id, scope=Scope.WRITE)
        if not authorized:
            raise errors.MissingResourceError(
                message=f"Project with id '{project_id}' does not exist or you do not have access to it."
            )

        async with self.session_maker() as session:
            async with session.begin():
                result = await session.execute(select(schemas.ProjectORM).where(schemas.ProjectORM.id == project_id))
                project = result.one_or_none()
                if project is None:
                    raise errors.MissingResourceError(message=f"The project with id '{project_id}' cannot be found")

                await self.project_authz.delete_user(requested_by=user, project_id=project_id, user_id=member_id)
