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
from renku_data_services.session import models
from renku_data_services.session import orm as schemas


class SessionRepository:
    """Repository for sessions."""

    def __init__(
        self, session_maker: Callable[..., AsyncSession], project_authz: Authz, resource_pools: ResourcePoolRepository
    ) -> None:
        self.session_maker = session_maker
        self.project_authz: Authz = project_authz
        self.resource_pools: ResourcePoolRepository = resource_pools

    async def get_environments(self) -> list[models.Environment]:
        """Get all global session environments from the database."""
        async with self.session_maker() as session:
            res = await session.scalars(
                select(schemas.EnvironmentORM).where(
                    schemas.EnvironmentORM.environment_kind == models.EnvironmentKind.GLOBAL.value
                )
            )
            environments = res.all()
            return [e.dump() for e in environments]

    async def get_environment(self, environment_id: ULID) -> models.Environment:
        """Get one global session environment from the database."""
        async with self.session_maker() as session:
            res = await session.scalars(
                select(schemas.EnvironmentORM)
                .where(schemas.EnvironmentORM.id == str(environment_id))
                .where(schemas.EnvironmentORM.environment_kind == models.EnvironmentKind.GLOBAL.value)
            )
            environment = res.one_or_none()
            if environment is None:
                raise errors.MissingResourceError(
                    message=f"Session environment with id '{environment_id}' does not exist or you do not have access to it."  # noqa: E501
                )
            return environment.dump()

    async def __insert_environment(
        self, user: base_models.APIUser, new_environment: models.UnsavedEnvironment
    ) -> schemas.EnvironmentORM:
        if user.id is None:
            raise errors.Unauthorized(
                message="You have to be authenticated to insert an environment in the DB.", quiet=True
            )
        environment = schemas.EnvironmentORM(
            name=new_environment.name,
            created_by_id=user.id,
            creation_date=datetime.now(UTC),
            description=new_environment.description,
            container_image=new_environment.container_image,
            default_url=new_environment.default_url,
            port=new_environment.port,
            working_directory=new_environment.working_directory.as_posix(),
            mount_directory=new_environment.mount_directory.as_posix(),
            uid=new_environment.uid,
            gid=new_environment.gid,
            environment_kind=new_environment.environment_kind,
        )

        async with self.session_maker() as session, session.begin():
            session.add(environment)
            return environment

    async def insert_environment(
        self, user: base_models.APIUser, new_environment: models.UnsavedEnvironment
    ) -> models.Environment:
        """Insert a new global session environment."""
        if user.id is None or not user.is_admin:
            raise errors.Unauthorized(
                message="You do not have the required permissions for this operation.", quiet=True
            )
        if new_environment.environment_kind != models.EnvironmentKind.GLOBAL:
            raise errors.ValidationError(message="This endpoint only supports adding global environments", quiet=True)

        env = await self.__insert_environment(user, new_environment)
        return env.dump()

    async def __update_environment(
        self, user: base_models.APIUser, environment_id: ULID, kind: models.EnvironmentKind, **kwargs: dict
    ) -> models.Environment:
        async with self.session_maker() as session, session.begin():
            res = await session.scalars(
                select(schemas.EnvironmentORM)
                .where(schemas.EnvironmentORM.id == str(environment_id))
                .where(schemas.EnvironmentORM.environment_kind == kind.value)
            )
            environment = res.one_or_none()
            if environment is None:
                raise errors.MissingResourceError(
                    message=f"Session environment with id '{environment_id}' does not exist."
                )

            for key, value in kwargs.items():
                # NOTE: Only some fields can be edited
                if key in [
                    "name",
                    "description",
                    "container_image",
                    "default_url",
                    "port",
                    "working_directory",
                    "mount_directory",
                    "uid",
                    "gid",
                ]:
                    setattr(environment, key, value)

            return environment.dump()

    async def update_environment(
        self, user: base_models.APIUser, environment_id: ULID, **kwargs: dict
    ) -> models.Environment:
        """Update a global session environment entry."""
        if not user.is_admin:
            raise errors.Unauthorized(message="You do not have the required permissions for this operation.")

        return await self.__update_environment(user, environment_id, models.EnvironmentKind.GLOBAL, **kwargs)

    async def delete_environment(self, user: base_models.APIUser, environment_id: ULID) -> None:
        """Delete a global session environment entry."""
        if not user.is_admin:
            raise errors.Unauthorized(message="You do not have the required permissions for this operation.")

        async with self.session_maker() as session, session.begin():
            res = await session.scalars(
                select(schemas.EnvironmentORM)
                .where(schemas.EnvironmentORM.id == str(environment_id))
                .where(schemas.EnvironmentORM.environment_kind == models.EnvironmentKind.GLOBAL.value)
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

    async def get_project_launchers(self, user: base_models.APIUser, project_id: str) -> list[models.SessionLauncher]:
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
                select(schemas.SessionLauncherORM).where(schemas.SessionLauncherORM.id == str(launcher_id))
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
        self, user: base_models.APIUser, new_launcher: models.UnsavedSessionLauncher
    ) -> models.SessionLauncher:
        """Insert a new session launcher."""
        if not user.is_authenticated or user.id is None:
            raise errors.Unauthorized(message="You do not have the required permissions for this operation.")

        project_id = new_launcher.project_id
        authorized = await self.project_authz.has_permission(user, ResourceType.project, project_id, Scope.WRITE)
        if not authorized:
            raise errors.MissingResourceError(
                message=f"Project with id '{project_id}' does not exist or you do not have access to it."
            )

        async with self.session_maker() as session, session.begin():
            res = await session.scalars(select(schemas.ProjectORM).where(schemas.ProjectORM.id == project_id))
            project = res.one_or_none()
            if project is None:
                raise errors.MissingResourceError(
                    message=f"Project with id '{project_id}' does not exist or you do not have access to it."
                )

            environment_id: str
            environment: models.Environment
            environment_orm: schemas.EnvironmentORM | None
            if isinstance(new_launcher.environment, models.UnsavedEnvironment):
                environment_orm = await self.__insert_environment(user, new_launcher.environment)
                environment = environment_orm.dump()
                environment_id = environment.id
            else:
                res_env = await session.scalars(
                    select(schemas.EnvironmentORM)
                    .where(schemas.EnvironmentORM.id == environment_id)
                    .where(schemas.EnvironmentORM.environment_kind == models.EnvironmentKind.GLOBAL.value)
                )
                environment_orm = res_env.one_or_none()
                if environment_orm is None:
                    raise errors.MissingResourceError(
                        message=f"Session environment with id '{environment_id}' does not exist or you do not have access to it."  # noqa: E501
                    )
                environment = environment_orm.dump()

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
                    raise errors.Unauthorized(
                        message=f"Resource class with id '{resource_class_id}' you do not have access to it."
                    )

            launcher = schemas.SessionLauncherORM(
                name=new_launcher.name,
                created_by_id=user.id,
                creation_date=datetime.now(UTC),
                description=new_launcher.description,
                project_id=new_launcher.project_id,
                environment_id=environment_id,
                resource_class_id=new_launcher.resource_class_id,
            )
            session.add(launcher)
            return launcher.dump()

    async def update_launcher(
        self, user: base_models.APIUser, launcher_id: ULID, **kwargs: Any
    ) -> models.SessionLauncher:
        """Update a session launcher entry."""
        if not user.is_authenticated or user.id is None:
            raise errors.Unauthorized(message="You do not have the required permissions for this operation.")

        async with self.session_maker() as session, session.begin():
            res = await session.scalars(
                select(schemas.SessionLauncherORM).where(schemas.SessionLauncherORM.id == str(launcher_id))
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
                raise errors.Unauthorized(message="You do not have the required permissions for this operation.")

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
                    raise errors.Unauthorized(
                        message=f"Resource class with id '{resource_class_id}' you do not have access to it."
                    )

            for key, value in kwargs.items():
                # NOTE: Only some fields can be updated.
                if key in [
                    "name",
                    "description",
                    "resource_class_id",
                ]:
                    setattr(launcher, key, value)

            env_payload: dict = kwargs.get("environment", {})
            if len(env_payload.keys()) == 1 and "id" in env_payload and isinstance(env_payload["id"], str):
                # The environment ID is being changed or set
                old_environment = launcher.environment
                new_environment_id = env_payload["id"]
                res_env = await session.scalars(
                    select(schemas.EnvironmentORM).where(schemas.EnvironmentORM.id == new_environment_id)
                )
                new_environment = res_env.one_or_none()
                if new_environment is None:
                    raise errors.MissingResourceError(
                        message=f"Session environment with id '{new_environment_id}' does not exist or "
                        "you do not have access to it."
                    )
                if new_environment.environment_kind != models.EnvironmentKind.GLOBAL:
                    raise errors.ValidationError(
                        message="Cannot set the environment for a launcher to an existing environment if that "
                        "existing environment is not global",
                        quiet=True,
                    )
                launcher.environment_id = new_environment_id
                launcher.environment = new_environment
                if old_environment.environment_kind == models.EnvironmentKind.CUSTOM:
                    # A custom environment exists but it is being updated to a global one
                    # We remove the custom environment to avoid accumulating custom environments that are not associated
                    # with any launchers.
                    await session.delete(old_environment)
            else:
                # Fields other than the environment ID are being updated
                if launcher.environment.environment_kind == models.EnvironmentKind.GLOBAL:
                    # A global environment is being replaced with a custom one
                    if env_payload.get("environment_kind") == models.EnvironmentKind.GLOBAL:
                        raise errors.ValidationError(
                            message="When one global environment is being replaced with another in a "
                            "launcher only the new global environment ID should be specfied",
                            quiet=True,
                        )
                    env_payload["environment_kind"] = models.EnvironmentKind.CUSTOM
                    try:
                        new_unsaved_env = models.UnsavedEnvironment(**env_payload)
                    except TypeError:
                        raise errors.ValidationError(
                            message="The payload for the new custom environment is not valid", quiet=True
                        )
                    new_env = await self.__insert_environment(user, new_unsaved_env)
                    launcher.environment = new_env
                else:
                    # Fields on the environment attached to the launcher are being changed.
                    for key, val in env_payload:
                        # NOTE: Only some fields can be updated.
                        if key in [
                            "name",
                            "description",
                            "container_image",
                            "default_url",
                            "port",
                            "working_directory",
                            "mount_directory",
                            "uid",
                            "gid",
                        ]:
                            setattr(launcher.environment, key, value)

            return launcher.dump()

    async def delete_launcher(self, user: base_models.APIUser, launcher_id: ULID) -> None:
        """Delete a session launcher entry."""
        if not user.is_authenticated or user.id is None:
            raise errors.Unauthorized(message="You do not have the required permissions for this operation.")

        async with self.session_maker() as session, session.begin():
            res = await session.scalars(
                select(schemas.SessionLauncherORM).where(schemas.SessionLauncherORM.id == str(launcher_id))
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
                raise errors.Unauthorized(message="You do not have the required permissions for this operation.")

            await session.delete(launcher)
            if launcher.environment.environment_kind == models.EnvironmentKind.CUSTOM:
                await session.delete(launcher.environment)
