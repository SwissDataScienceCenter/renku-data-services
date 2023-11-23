"""Adapters for project database classes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, NamedTuple, Tuple, cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.project import models
from renku_data_services.project import orm as schemas


class PaginationResponse(NamedTuple):
    """Paginated response."""

    page: int
    per_page: int
    total: int
    total_pages: int


class ProjectRepository:
    """Repository for project."""

    def __init__(self, session_maker: Callable[..., AsyncSession]):
        self.session_maker = session_maker  # type: ignore[call-overload]

    async def get_projects(
        self, user: base_models.APIUser, page: int, per_page: int
    ) -> Tuple[list[models.Project], PaginationResponse]:
        """Get all projects from the database."""
        if page < 1:
            raise errors.ValidationError(message="Parameter 'page' must be a natural number")
        if per_page < 1 or per_page > 100:
            raise errors.ValidationError(message="Parameter 'per_page' must be between 1 and 100")

        async with self.session_maker() as session:
            stmt = select(schemas.ProjectORM)
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

            # TODO: Filter based on the APIUser

            return [p.dump() for p in projects_orm], pagination

    async def get_project(self, user: base_models.APIUser, id: str) -> models.Project:
        """Get one project from the database."""
        async with self.session_maker() as session:
            stmt = select(schemas.ProjectORM).where(schemas.ProjectORM.id == id)
            result = await session.execute(stmt)
            project_orm = result.scalars().first()

            # TODO: Filter based on the APIUser

            if project_orm is None:
                raise errors.MissingResourceError(message=f"Project with id {id} does not exist.")

            return project_orm.dump()

    async def insert_project(self, user: base_models.APIUser, project: models.Project) -> models.Project:
        """Insert a new project entry."""
        project_orm = schemas.ProjectORM.load(project)
        project_orm.creation_date = datetime.now(timezone.utc).replace(microsecond=0)
        project_orm.created_by = user.id

        async with self.session_maker() as session:
            async with session.begin():
                session.add(project_orm)

        return project_orm.dump()

    async def update_project(self, user: base_models.APIUser, id: str, **kwargs) -> models.Project:
        """Update a project entry."""
        async with self.session_maker() as session:
            async with session.begin():
                result = await session.execute(select(schemas.ProjectORM).where(schemas.ProjectORM.id == id))
                projects = result.one_or_none()

                if projects is None:
                    raise errors.MissingResourceError(message=f"The project with id '{id}' cannot be found")

                # TODO: Check if the user can access this project

                project = projects[0]

                if "id" in kwargs and kwargs["id"] != project.id:
                    raise errors.ValidationError(message="Cannot change 'id' of existing project.")
                # TODO: What about created_by and date_created

                for key, value in kwargs.items():
                    setattr(project, key, value)

                return project.dump()  # NOTE: Triggers validation before the transaction saves data

    async def delete_project(self, user: base_models.APIUser, id: str) -> None:
        """Delete a cloud project entry."""
        async with self.session_maker() as session:
            async with session.begin():
                result = await session.execute(select(schemas.ProjectORM).where(schemas.ProjectORM.id == id))
                projects = result.one_or_none()

                if projects is None:
                    return

                # TODO: Check if the user can access this project

                await session.delete(projects[0])
