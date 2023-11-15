"""Adapters for project database classes."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.project import models
from renku_data_services.project import orm as schemas


class _Base:
    """Base class for repositories."""

    def __init__(self, sync_sqlalchemy_url: str, async_sqlalchemy_url: str, debug: bool = False):
        self.engine = create_async_engine(async_sqlalchemy_url, echo=debug)
        self.sync_engine = create_engine(sync_sqlalchemy_url, echo=debug)
        self.session_maker = sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)  # type: ignore


class ProjectRepository(_Base):
    """Repository for project."""

    async def get_projects(self, user: base_models.APIUser) -> list[models.Project]:
        """Get all projects from the database."""
        async with self.session_maker() as session:
            stmt = select(schemas.ProjectORM)
            result = await session.execute(stmt)
            projects_orm = result.scalars().all()

            # TODO: Filter based on the APIUser

            return [p.dump() for p in projects_orm]

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
