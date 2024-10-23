"""Adapters for session database classes."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.authz.authz import Authz, ResourceType
from renku_data_services.authz.models import Scope
from renku_data_services.crc.db import ResourcePoolRepository
from renku_data_services.session import apispec, models
from renku_data_services.session import orm as schemas
from renku_data_services.session.apispec import EnvironmentKind


class SessionRepository:
    """Repository for sessions."""

    def __init__(
        self, session_maker: Callable[..., AsyncSession], project_authz: Authz, resource_pools: ResourcePoolRepository
    ) -> None:
        self.session_maker = session_maker
        self.project_authz: Authz = project_authz
        self.resource_pools: ResourcePoolRepository = resource_pools

    async def get_environments(self) -> list[models.Environment]:
        """Get all session environments from the database."""
        async with self.session_maker() as session:
            res = await session.scalars(select(schemas.EnvironmentORM))
            environments = res.all()
            return [e.dump() for e in environments]

    async def get_environment(self, environment_id: ULID) -> models.Environment:
        """Get one session environment from the database."""
        async with self.session_maker() as session:
            res = await session.scalars(
                select(schemas.EnvironmentORM).where(schemas.EnvironmentORM.id == str(environment_id))
            )
            environment = res.one_or_none()
            if environment is None:
                raise errors.MissingResourceError(
                    message=f"Session environment with id '{environment_id}' does not exist or you do not have access to it."  # noqa: E501
                )
            return environment.dump()

    async def insert_environment(
        self,
        user: base_models.APIUser,
        new_environment: apispec.EnvironmentPost,
    ) -> models.Environment:
        """Insert a new session environment."""
        if user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")
        if not user.is_admin:
            raise errors.ForbiddenError(message="You do not have the required permissions for this operation.")

        environment_model = models.Environment(
            id=None,
            name=new_environment.name,
            description=new_environment.description,
            container_image=new_environment.container_image,
            default_url=new_environment.default_url,
            created_by=models.Member(id=user.id),
            creation_date=datetime.now(UTC).replace(microsecond=0),
        )
        environment = schemas.EnvironmentORM.load(environment_model)

        async with self.session_maker() as session, session.begin():
            session.add(environment)
            return environment.dump()

    async def update_environment(
        self, user: base_models.APIUser, environment_id: ULID, **kwargs: dict
    ) -> models.Environment:
        """Update a session environment entry."""
        if not user.is_admin:
            raise errors.ForbiddenError(message="You do not have the required permissions for this operation.")

        async with self.session_maker() as session, session.begin():
            res = await session.scalars(
                select(schemas.EnvironmentORM).where(schemas.EnvironmentORM.id == str(environment_id))
            )
            environment = res.one_or_none()
            if environment is None:
                raise errors.MissingResourceError(
                    message=f"Session environment with id '{environment_id}' does not exist."
                )

            for key, value in kwargs.items():
                # NOTE: Only ``name``, ``description``, ``container_image`` and ``default_url`` can be edited
                if key in ["name", "description", "container_image", "default_url"]:
                    setattr(environment, key, value)

            return environment.dump()

    async def delete_environment(self, user: base_models.APIUser, environment_id: ULID) -> None:
        """Delete a session environment entry."""
        if not user.is_admin:
            raise errors.ForbiddenError(message="You do not have the required permissions for this operation.")

        async with self.session_maker() as session, session.begin():
            res = await session.scalars(
                select(schemas.EnvironmentORM).where(schemas.EnvironmentORM.id == str(environment_id))
            )
            environment = res.one_or_none()

            if environment is None:
                return

            await session.delete(environment)

    async def get_launchers(self, user: base_models.APIUser) -> list[models.SessionLauncher]:
        """Get all session launchers visible for a specific user from the database."""
        project_ids = await self.project_authz.resources_with_permission(
            user, user.id, ResourceType.project, scope=Scope.READ
        )

        async with self.session_maker() as session:
            res = await session.scalars(
                select(schemas.SessionLauncherORM)
                .where(schemas.SessionLauncherORM.project_id.in_(project_ids))
                .order_by(schemas.SessionLauncherORM.creation_date.desc())
            )
            launcher = res.all()
            return [item.dump() for item in launcher]

    async def get_project_launchers(self, user: base_models.APIUser, project_id: ULID) -> list[models.SessionLauncher]:
        """Get all session launchers in a project from the database."""
        authorized = await self.project_authz.has_permission(user, ResourceType.project, project_id, Scope.READ)
        if not authorized:
            raise errors.MissingResourceError(
                message=f"Project with id '{project_id}' does not exist or you do not have access to it."
            )

        async with self.session_maker() as session:
            res = await session.scalars(
                select(schemas.SessionLauncherORM)
                .where(schemas.SessionLauncherORM.project_id == project_id)
                .order_by(schemas.SessionLauncherORM.creation_date.desc())
            )
            launcher = res.all()
            return [item.dump() for item in launcher]

    async def get_launcher(self, user: base_models.APIUser, launcher_id: ULID) -> models.SessionLauncher:
        """Get one session launcher from the database."""
        async with self.session_maker() as session:
            res = await session.scalars(
                select(schemas.SessionLauncherORM).where(schemas.SessionLauncherORM.id == launcher_id)
            )
            launcher = res.one_or_none()

            authorized = (
                await self.project_authz.has_permission(user, ResourceType.project, launcher.project_id, Scope.READ)
                if launcher is not None
                else False
            )
            if not authorized or launcher is None:
                raise errors.MissingResourceError(
                    message=f"Session launcher with id '{launcher_id}' does not exist or you do not have access to it."
                )

            return launcher.dump()

    async def insert_launcher(
        self, user: base_models.APIUser, new_launcher: apispec.SessionLauncherPost
    ) -> models.SessionLauncher:
        """Insert a new session launcher."""
        if not user.is_authenticated or user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")

        project_id = new_launcher.project_id
        authorized = await self.project_authz.has_permission(
            user, ResourceType.project, ULID.from_str(project_id), Scope.WRITE
        )
        if not authorized:
            raise errors.MissingResourceError(
                message=f"Project with id '{project_id}' does not exist or you do not have access to it."
            )

        launcher_model = models.SessionLauncher(
            id=None,
            name=new_launcher.name,
            project_id=new_launcher.project_id,
            description=new_launcher.description,
            environment_kind=new_launcher.environment_kind,
            environment_id=new_launcher.environment_id,
            resource_class_id=new_launcher.resource_class_id,
            container_image=new_launcher.container_image,
            default_url=new_launcher.default_url,
            created_by=models.Member(id=user.id),
            creation_date=datetime.now(UTC).replace(microsecond=0),
        )

        models.SessionLauncher.model_validate(launcher_model)

        async with self.session_maker() as session, session.begin():
            res = await session.scalars(select(schemas.ProjectORM).where(schemas.ProjectORM.id == project_id))
            project = res.one_or_none()
            if project is None:
                raise errors.MissingResourceError(
                    message=f"Project with id '{project_id}' does not exist or you do not have access to it."
                )

            environment_id = new_launcher.environment_id
            if environment_id is not None:
                res = await session.scalars(
                    select(schemas.EnvironmentORM).where(schemas.EnvironmentORM.id == environment_id)
                )
                environment = res.one_or_none()
                if environment is None:
                    raise errors.MissingResourceError(
                        message=f"Session environment with id '{environment_id}' does not exist or you do not have access to it."  # noqa: E501
                    )

            resource_class_id = new_launcher.resource_class_id
            if resource_class_id is not None:
                res = await session.scalars(
                    select(schemas.ResourceClassORM).where(schemas.ResourceClassORM.id == resource_class_id)
                )
                resource_class = res.one_or_none()
                if resource_class is None:
                    raise errors.MissingResourceError(
                        message=f"Resource class with id '{resource_class_id}' does not exist."
                    )

                res_classes = await self.resource_pools.get_classes(api_user=user, id=resource_class_id)
                resource_class_by_user = next((rc for rc in res_classes if rc.id == resource_class_id), None)
                if resource_class_by_user is None:
                    raise errors.ForbiddenError(
                        message=f"You do not have access to resource class with id '{resource_class_id}'."
                    )

            launcher = schemas.SessionLauncherORM.load(launcher_model)
            session.add(launcher)
            return launcher.dump()

    async def update_launcher(
        self, user: base_models.APIUser, launcher_id: ULID, **kwargs: Any
    ) -> models.SessionLauncher:
        """Update a session launcher entry."""
        if not user.is_authenticated or user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")

        async with self.session_maker() as session, session.begin():
            res = await session.scalars(
                select(schemas.SessionLauncherORM).where(schemas.SessionLauncherORM.id == launcher_id)
            )
            launcher = res.one_or_none()
            if launcher is None:
                raise errors.MissingResourceError(
                    message=f"Session launcher with id '{launcher_id}' does not exist or you do not have access to it."  # noqa: E501
                )

            authorized = await self.project_authz.has_permission(
                user,
                ResourceType.project,
                launcher.project_id,
                Scope.WRITE,
            )
            if not authorized:
                raise errors.ForbiddenError(message="You do not have the required permissions for this operation.")

            environment_id = kwargs.get("environment_id")
            if environment_id is not None:
                res = await session.scalars(
                    select(schemas.EnvironmentORM).where(schemas.EnvironmentORM.id == environment_id)
                )
                environment = res.one_or_none()
                if environment is None:
                    raise errors.MissingResourceError(
                        message=f"Session environment with id '{environment_id}' does not exist or you do not have access to it."  # noqa: E501
                    )

            resource_class_id = kwargs.get("resource_class_id")
            if resource_class_id is not None:
                res = await session.scalars(
                    select(schemas.ResourceClassORM).where(schemas.ResourceClassORM.id == resource_class_id)
                )
                resource_class = res.one_or_none()
                if resource_class is None:
                    raise errors.MissingResourceError(
                        message=f"Resource class with id '{resource_class_id}' does not exist."
                    )

                res_classes = await self.resource_pools.get_classes(api_user=user, id=resource_class_id)
                resource_class_by_user = next((rc for rc in res_classes if rc.id == resource_class_id), None)
                if resource_class_by_user is None:
                    raise errors.ForbiddenError(
                        message=f"You do not have access to resource class with id '{resource_class_id}'."
                    )

            for key, value in kwargs.items():
                # NOTE: Only ``name``, ``description``, ``environment_kind``,
                #       ``environment_id``, ``resource_class_id``, ``container_image`` and
                #       ``default_url`` can be edited.
                if key in [
                    "name",
                    "description",
                    "environment_kind",
                    "environment_id",
                    "resource_class_id",
                    "container_image",
                    "default_url",
                ]:
                    setattr(launcher, key, value)

            if launcher.environment_kind == EnvironmentKind.global_environment:
                launcher.container_image = None
            if launcher.environment_kind == EnvironmentKind.container_image:
                launcher.environment = None

            launcher_model = launcher.dump()
            models.SessionLauncher.model_validate(launcher_model)

            return launcher_model

    async def delete_launcher(self, user: base_models.APIUser, launcher_id: ULID) -> None:
        """Delete a session launcher entry."""
        if not user.is_authenticated or user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")

        async with self.session_maker() as session, session.begin():
            res = await session.scalars(
                select(schemas.SessionLauncherORM).where(schemas.SessionLauncherORM.id == launcher_id)
            )
            launcher = res.one_or_none()

            if launcher is None:
                return

            authorized = await self.project_authz.has_permission(
                user,
                ResourceType.project,
                launcher.project_id,
                Scope.WRITE,
            )
            if not authorized:
                raise errors.ForbiddenError(message="You do not have the required permissions for this operation.")

            await session.delete(launcher)
