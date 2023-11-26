"""Adapters for project database classes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, NamedTuple, Tuple, cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.authz.authz import SQLProjectAuthorizer
from renku_data_services.authz.models import MemberQualifier, Scope
from renku_data_services.project import models
from renku_data_services.project import orm as schemas
from renku_data_services.project.apispec import Visibility


class PaginationResponse(NamedTuple):
    """Paginated response."""

    page: int
    per_page: int
    total: int
    total_pages: int


class ProjectRepository:
    """Repository for project."""

    def __init__(self, session_maker: Callable[..., AsyncSession], project_authz: SQLProjectAuthorizer):
        self.session_maker = session_maker  # type: ignore[call-overload]
        self.project_authz: SQLProjectAuthorizer = project_authz

    async def get_projects(
        self, user: base_models.APIUser, page: int, per_page: int
    ) -> Tuple[list[models.Project], PaginationResponse]:
        """Get all projects from the database."""
        if page < 1:
            raise errors.ValidationError(message="Parameter 'page' must be a natural number")
        if per_page < 1 or per_page > 100:
            raise errors.ValidationError(message="Parameter 'per_page' must be between 1 and 100")

        user_id = user.id if user.is_authenticated else MemberQualifier.ALL
        project_ids = await self.project_authz.get_user_projects(requested_by=user, user_id=user_id, scope=Scope.READ)

        async with self.session_maker() as session:
            stmt = select(schemas.ProjectORM)
            stmt = stmt.where(schemas.ProjectORM.id.in_(project_ids))
            stmt = stmt.limit(per_page).offset((page - 1) * per_page)
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
            raise errors.Unauthorized(message="You do not have the required permissions to access this project.")

        async with self.session_maker() as session:
            stmt = select(schemas.ProjectORM).where(schemas.ProjectORM.id == project_id)
            result = await session.execute(stmt)
            project_orm = result.scalars().first()

            if project_orm is None:
                raise errors.MissingResourceError(message=f"Project with id '{project_id}' does not exist.")

            return project_orm.dump()

    async def insert_project(self, user: base_models.APIUser, project: models.Project) -> models.Project:
        """Insert a new project entry."""
        project_orm = schemas.ProjectORM.load(project)
        project_orm.creation_date = datetime.now(timezone.utc).replace(microsecond=0)
        project_orm.created_by = user.id

        async with self.session_maker() as session:
            async with session.begin():
                session.add(project_orm)

                # TODO: Test that raising an exception causes the transaction to be aborted or not

                project = project_orm.dump()
                public_project = project.visibility == Visibility.public
                await self.project_authz.create_project(
                    requested_by=user, project_id=project.id, public_project=public_project
                )

        return project_orm.dump()

    async def update_project(self, user: base_models.APIUser, project_id: str, **kwargs) -> models.Project:
        """Update a project entry."""
        authorized = await self.project_authz.has_permission(user=user, project_id=project_id, scope=Scope.WRITE)
        if not authorized:
            raise errors.Unauthorized(message="You do not have the required permissions to update the project.")

        async with self.session_maker() as session:
            async with session.begin():
                result = await session.execute(select(schemas.ProjectORM).where(schemas.ProjectORM.id == project_id))
                projects = result.one_or_none()

                if projects is None:
                    raise errors.MissingResourceError(message=f"The project with id '{project_id}' cannot be found")

                project = projects[0]

                for key, value in kwargs.items():
                    # NOTE: ``slug``, ``id``, ``created_by``, and ``creation_date`` cannot be edited
                    if key not in ["slug", "id", "created_by", "creation_date"]:
                        setattr(project, key, value)

                # TODO: Update members -> Add, remove members

                return project.dump()  # NOTE: Triggers validation before the transaction saves data

    async def delete_project(self, user: base_models.APIUser, project_id: str) -> None:
        """Delete a cloud project entry."""
        authorized = await self.project_authz.has_permission(user=user, project_id=project_id, scope=Scope.DELETE)
        if not authorized:
            raise errors.Unauthorized(message="You do not have the required permissions to delete the project.")

        async with self.session_maker() as session:
            async with session.begin():
                result = await session.execute(select(schemas.ProjectORM).where(schemas.ProjectORM.id == project_id))
                projects = result.one_or_none()

                if projects is None:
                    return

                await session.delete(projects[0])
