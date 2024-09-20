"""Adapters for session database classes."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager, nullcontext
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
        self,
        user: base_models.APIUser,
        session: AsyncSession,
        new_environment: models.UnsavedEnvironment,
    ) -> schemas.EnvironmentORM:
        if user.id is None:
            raise errors.UnauthorizedError(
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
            working_directory=new_environment.working_directory,
            mount_directory=new_environment.mount_directory,
            uid=new_environment.uid,
            gid=new_environment.gid,
            environment_kind=new_environment.environment_kind,
            command=new_environment.command,
            args=new_environment.args,
        )

        session.add(environment)
        return environment

    async def insert_environment(
        self, user: base_models.APIUser, new_environment: models.UnsavedEnvironment
    ) -> models.Environment:
        """Insert a new global session environment."""
        if user.id is None or not user.is_admin:
            raise errors.UnauthorizedError(
                message="You do not have the required permissions for this operation.", quiet=True
            )
        if new_environment.environment_kind != models.EnvironmentKind.GLOBAL:
            raise errors.ValidationError(message="This endpoint only supports adding global environments", quiet=True)

        async with self.session_maker() as session, session.begin():
            env = await self.__insert_environment(user, session, new_environment)
            return env.dump()

    async def __update_environment(
        self,
        user: base_models.APIUser,
        session: AsyncSession,
        environment_id: ULID,
        kind: models.EnvironmentKind,
        **kwargs: dict,
    ) -> models.Environment:
        res = await session.scalars(
            select(schemas.EnvironmentORM)
            .where(schemas.EnvironmentORM.id == str(environment_id))
            .where(schemas.EnvironmentORM.environment_kind == kind.value)
        )
        environment = res.one_or_none()
        if environment is None:
            raise errors.MissingResourceError(message=f"Session environment with id '{environment_id}' does not exist.")

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
                "args",
                "command",
            ]:
                setattr(environment, key, value)

        return environment.dump()

    async def update_environment(
        self, user: base_models.APIUser, environment_id: ULID, **kwargs: dict
    ) -> models.Environment:
        """Update a global session environment entry."""
        if not user.is_admin:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")

        async with self.session_maker() as session, session.begin():
            return await self.__update_environment(
                user, session, environment_id, models.EnvironmentKind.GLOBAL, **kwargs
            )

    async def delete_environment(self, user: base_models.APIUser, environment_id: ULID) -> None:
        """Delete a global session environment entry."""
        if not user.is_admin:
            raise errors.ForbiddenError(message="You do not have the required permissions for this operation.")

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
        authorized = await self.project_authz.has_permission(
            user, ResourceType.project, ULID.from_str(project_id), Scope.READ
        )
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
        self, user: base_models.APIUser, new_launcher: models.UnsavedSessionLauncher
    ) -> models.SessionLauncher:
        """Insert a new session launcher."""
        if not user.is_authenticated or user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")

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

            environment_id: ULID
            environment: models.Environment
            environment_orm: schemas.EnvironmentORM | None
            if isinstance(new_launcher.environment, models.UnsavedEnvironment):
                environment_orm = await self.__insert_environment(user, session, new_launcher.environment)
                environment = environment_orm.dump()
                environment_id = environment.id
            else:
                environment_id = ULID.from_str(new_launcher.environment)
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
                    raise errors.ForbiddenError(
                        message=f"You do not have access to resource class with id '{resource_class_id}'."
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
            await session.flush()
            await session.refresh(launcher)
            return launcher.dump()

    async def update_launcher(
        self,
        user: base_models.APIUser,
        launcher_id: ULID,
        new_custom_environment: models.UnsavedEnvironment | None,
        session: AsyncSession | None = None,
        **kwargs: Any,
    ) -> models.SessionLauncher:
        """Update a session launcher entry."""
        if not user.is_authenticated or user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")

        session_ctx: AbstractAsyncContextManager = nullcontext()
        tx: AbstractAsyncContextManager = nullcontext()
        if not session:
            session = self.session_maker()
            session_ctx = session
        if not session.in_transaction():
            tx = session.begin()

        async with session_ctx, tx:
            res = await session.scalars(
                select(schemas.SessionLauncherORM).where(schemas.SessionLauncherORM.id == launcher_id)
            )
            launcher = res.one_or_none()
            if launcher is None:
                raise errors.MissingResourceError(
                    message=f"Session launcher with id '{launcher_id}' does not "
                    "exist or you do not have access to it."
                )

            authorized = await self.project_authz.has_permission(
                user,
                ResourceType.project,
                launcher.project_id,
                Scope.WRITE,
            )
            if not authorized:
                raise errors.ForbiddenError(message="You do not have the required permissions for this operation.")

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
                # NOTE: Only some fields can be updated.
                if key in [
                    "name",
                    "description",
                    "resource_class_id",
                ]:
                    setattr(launcher, key, value)

            env_payload = kwargs.get("environment", {})
            await self.__update_launcher_environment(user, launcher, session, new_custom_environment, **env_payload)
            return launcher.dump()

    async def __update_launcher_environment(
        self,
        user: base_models.APIUser,
        launcher: schemas.SessionLauncherORM,
        session: AsyncSession,
        new_custom_environment: models.UnsavedEnvironment | None,
        **kwargs: Any,
    ) -> None:
        current_env_kind = launcher.environment.environment_kind
        match new_custom_environment, current_env_kind, kwargs:
            case None, _, {"id": env_id, **nothing_else} if len(nothing_else) == 0:
                # The environment in the launcher is set via ID, the new ID has to refer
                # to an environment that is GLOBAL.
                old_environment = launcher.environment
                new_environment_id = ULID.from_str(env_id)
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
            case None, models.EnvironmentKind.CUSTOM, {**rest} if (
                rest.get("environment_kind") is None
                or rest.get("environment_kind") == models.EnvironmentKind.CUSTOM.value
            ):
                # Custom environment being updated
                for key, val in rest.items():
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
                        "args",
                        "command",
                    ]:
                        setattr(launcher.environment, key, val)
            case models.UnsavedEnvironment(), models.EnvironmentKind.GLOBAL, {**nothing_else} if (
                len(nothing_else) == 0 and new_custom_environment.environment_kind == models.EnvironmentKind.CUSTOM
            ):
                # Global environment replaced by a custom one
                new_env = await self.__insert_environment(user, session, new_custom_environment)
                launcher.environment = new_env
            case _:
                raise errors.ValidationError(
                    message="Encountered an invalid payload for updating a launcher environment", quiet=True
                )

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
            if launcher.environment.environment_kind == models.EnvironmentKind.CUSTOM:
                await session.delete(launcher.environment)
