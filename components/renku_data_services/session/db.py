"""Adapters for session database classes."""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager, nullcontext
from datetime import UTC, datetime
from pathlib import PurePosixPath

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.app_config.config import BuildsConfig
from renku_data_services.authz.authz import Authz, ResourceType
from renku_data_services.authz.models import Scope
from renku_data_services.base_models.core import RESET
from renku_data_services.crc.db import ResourcePoolRepository
from renku_data_services.session import constants, models, shipwright_core
from renku_data_services.session import orm as schemas
from renku_data_services.session.shipwright_client import ShipwrightClient


class SessionRepository:
    """Repository for sessions."""

    def __init__(
        self,
        session_maker: Callable[..., AsyncSession],
        project_authz: Authz,
        resource_pools: ResourcePoolRepository,
        shipwright_client: ShipwrightClient | None,
        builds_config: BuildsConfig,
    ) -> None:
        self.session_maker = session_maker
        self.project_authz: Authz = project_authz
        self.resource_pools: ResourcePoolRepository = resource_pools
        self.shipwright_client = shipwright_client
        self.builds_config = builds_config

        # TODO: remove this later?
        logging.info(f"BUILDS_ENABLED={self.builds_config.enabled}")
        if self.builds_config.enabled:
            logging.info(f"build_output_image_prefix={self.builds_config.build_output_image_prefix}")
            logging.info(f"vscodium_python_run_image={self.builds_config.vscodium_python_run_image}")
            logging.info(f"build_strategy_name={self.builds_config.build_strategy_name}")
            logging.info(f"push_secret_name={self.builds_config.push_secret_name}")

    async def get_environments(self, include_archived: bool = False) -> list[models.Environment]:
        """Get all global session environments from the database."""
        async with self.session_maker() as session:
            statement = select(schemas.EnvironmentORM).where(
                schemas.EnvironmentORM.environment_kind == models.EnvironmentKind.GLOBAL.value
            )
            if not include_archived:
                statement = statement.where(schemas.EnvironmentORM.is_archived.is_(False))
            res = await session.scalars(statement)
            environments = res.all()
            return [e.dump() for e in environments]

    async def get_environment(self, environment_id: ULID) -> models.Environment:
        """Get one global session environment from the database."""
        async with self.session_maker() as session:
            res = await session.scalars(
                select(schemas.EnvironmentORM)
                .where(schemas.EnvironmentORM.id == environment_id)
                .where(schemas.EnvironmentORM.environment_kind == models.EnvironmentKind.GLOBAL.value)
            )
            environment = res.one_or_none()
            if environment is None:
                raise errors.MissingResourceError(
                    message=f"Session environment with id '{environment_id}' does not exist or you do not have access to it."  # noqa: E501
                )
            return environment.dump()

    def __insert_environment(
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
            creation_date=datetime.now(UTC).replace(microsecond=0),
            is_archived=new_environment.is_archived,
        )

        session.add(environment)
        return environment

    async def insert_environment(
        self, user: base_models.APIUser, environment: models.UnsavedEnvironment
    ) -> models.Environment:
        """Insert a new session environment."""
        if user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")
        if not user.is_admin:
            raise errors.ForbiddenError(message="You do not have the required permissions for this operation.")
        if environment.environment_kind != models.EnvironmentKind.GLOBAL:
            raise errors.ValidationError(message="This endpoint only supports adding global environments", quiet=True)

        async with self.session_maker() as session, session.begin():
            env = self.__insert_environment(user, session, environment)
            await session.flush()
            await session.refresh(env)
            return env.dump()

    def __update_environment(
        self,
        environment: schemas.EnvironmentORM,
        update: models.EnvironmentPatch,
    ) -> None:
        # NOTE: this is more verbose than a loop and setattr but this way we get mypy type checks
        if update.name is not None:
            environment.name = update.name
        if update.description is not None:
            environment.description = update.description
        if update.container_image is not None:
            environment.container_image = update.container_image
        if update.default_url is not None:
            environment.default_url = update.default_url
        if update.port is not None:
            environment.port = update.port
        if update.working_directory is not None and update.working_directory is RESET:
            environment.working_directory = None
        elif update.working_directory is not None and isinstance(update.working_directory, PurePosixPath):
            environment.working_directory = update.working_directory
        if update.mount_directory is not None and update.mount_directory is RESET:
            environment.mount_directory = None
        elif update.mount_directory is not None and isinstance(update.mount_directory, PurePosixPath):
            environment.mount_directory = update.mount_directory
        if update.uid is not None:
            environment.uid = update.uid
        if update.gid is not None:
            environment.gid = update.gid
        if update.args is RESET:
            environment.args = None
        elif isinstance(update.args, list):
            environment.args = update.args
        if update.command is RESET:
            environment.command = None
        elif isinstance(update.command, list):
            environment.command = update.command

        if update.is_archived is not None:
            environment.is_archived = update.is_archived

    async def update_environment(
        self, user: base_models.APIUser, environment_id: ULID, patch: models.EnvironmentPatch
    ) -> models.Environment:
        """Update a global session environment entry."""
        if not user.is_admin:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")

        async with self.session_maker() as session, session.begin():
            res = await session.scalars(
                select(schemas.EnvironmentORM)
                .where(schemas.EnvironmentORM.id == str(environment_id))
                .where(schemas.EnvironmentORM.environment_kind == models.EnvironmentKind.GLOBAL)
            )
            environment = res.one_or_none()
            if environment is None:
                raise errors.MissingResourceError(
                    message=f"Session environment with id '{environment_id}' does not exist."
                )

            self.__update_environment(environment, patch)
            return environment.dump()

    async def delete_environment(self, user: base_models.APIUser, environment_id: ULID) -> None:
        """Delete a global session environment entry."""
        if not user.is_admin:
            raise errors.ForbiddenError(message="You do not have the required permissions for this operation.")

        async with self.session_maker() as session, session.begin():
            res = await session.scalars(
                select(schemas.EnvironmentORM)
                .where(schemas.EnvironmentORM.id == environment_id)
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
        self, user: base_models.APIUser, launcher: models.UnsavedSessionLauncher
    ) -> models.SessionLauncher:
        """Insert a new session launcher."""
        if not user.is_authenticated or user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")

        project_id = launcher.project_id
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
            if isinstance(launcher.environment, models.UnsavedEnvironment):
                environment_orm = schemas.EnvironmentORM(
                    name=launcher.environment.name,
                    created_by_id=user.id,
                    description=launcher.environment.description,
                    container_image=launcher.environment.container_image,
                    default_url=launcher.environment.default_url,
                    port=launcher.environment.port,
                    working_directory=launcher.environment.working_directory,
                    mount_directory=launcher.environment.mount_directory,
                    uid=launcher.environment.uid,
                    gid=launcher.environment.gid,
                    environment_kind=launcher.environment.environment_kind,
                    command=launcher.environment.command,
                    args=launcher.environment.args,
                    creation_date=datetime.now(UTC).replace(microsecond=0),
                )
                session.add(environment_orm)
            else:
                environment_id = ULID.from_str(launcher.environment)
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
                if environment_orm.is_archived:
                    raise errors.ValidationError(
                        message="Cannot create a new session launcher with an archived environment."
                    )

            environment = environment_orm.dump()
            environment_id = environment.id

            resource_class_id = launcher.resource_class_id
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

            launcher_orm = schemas.SessionLauncherORM(
                name=launcher.name,
                project_id=launcher.project_id,
                description=launcher.description if launcher.description else None,
                environment_id=environment_id,
                resource_class_id=launcher.resource_class_id,
                disk_storage=launcher.disk_storage,
                created_by_id=user.id,
                creation_date=datetime.now(UTC).replace(microsecond=0),
            )
            session.add(launcher_orm)
            await session.flush()
            await session.refresh(launcher_orm)
            return launcher_orm.dump()

    async def copy_launcher(
        self, user: base_models.APIUser, project_id: ULID, launcher: models.SessionLauncher
    ) -> models.SessionLauncher:
        """Create a copy of the launcher in the given project."""
        if not user.is_authenticated or user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")

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

            launcher_orm = schemas.SessionLauncherORM(
                name=launcher.name,
                project_id=project_id,
                description=launcher.description,
                environment_id=launcher.environment.id,
                resource_class_id=launcher.resource_class_id,
                disk_storage=launcher.disk_storage,
                created_by_id=user.id,
                creation_date=datetime.now(UTC).replace(microsecond=0),
            )
            session.add(launcher_orm)
            await session.flush()
            await session.refresh(launcher_orm)
            return launcher_orm.dump()

    async def update_launcher(
        self,
        user: base_models.APIUser,
        launcher_id: ULID,
        patch: models.SessionLauncherPatch,
        session: AsyncSession | None = None,
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

            resource_class_id = patch.resource_class_id
            if isinstance(resource_class_id, int):
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

            # NOTE: Only some fields can be updated.
            if patch.name is not None:
                launcher.name = patch.name
            if patch.description is not None:
                launcher.description = patch.description
            if isinstance(patch.resource_class_id, int):
                launcher.resource_class_id = patch.resource_class_id
            elif patch.resource_class_id is RESET:
                launcher.resource_class_id = None
            if isinstance(patch.disk_storage, int):
                launcher.disk_storage = patch.disk_storage
            elif patch.disk_storage is RESET:
                launcher.disk_storage = None

            if patch.environment is None:
                return launcher.dump()

            await self.__update_launcher_environment(user, launcher, session, patch.environment)
            await session.flush()
            await session.refresh(launcher)
            return launcher.dump()

    async def __update_launcher_environment(
        self,
        user: base_models.APIUser,
        launcher: schemas.SessionLauncherORM,
        session: AsyncSession,
        update: models.EnvironmentPatch | models.UnsavedEnvironment | str,
    ) -> None:
        current_env_kind = launcher.environment.environment_kind
        match update, current_env_kind:
            case str() as env_id, _:
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
            case models.EnvironmentPatch(), models.EnvironmentKind.CUSTOM:
                # Custom environment being updated
                self.__update_environment(launcher.environment, update)
            case models.UnsavedEnvironment() as new_custom_environment, models.EnvironmentKind.GLOBAL if (
                new_custom_environment.environment_kind == models.EnvironmentKind.CUSTOM
            ):
                # Global environment replaced by a custom one
                new_env = self.__insert_environment(user, session, new_custom_environment)
                launcher.environment = new_env
                await session.flush()
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

    async def get_build(self, user: base_models.APIUser, build_id: ULID) -> models.Build:
        """Get a specific build."""

        # TODO: check READ permissions on this chain: build->environment->launcher->project

        async with self.session_maker() as session, session.begin():
            stmt = select(schemas.BuildORM).where(schemas.BuildORM.id == build_id)
            result = await session.scalars(stmt)
            build = result.one_or_none()

            if build is None:
                raise errors.MissingResourceError(
                    message=f"Build with id '{build_id}' does not exist or you do not have access to it."
                )

            # Check and refresh the status of in-progress builds
            await self._refresh_build(build=build, session=session)

            return build.dump()

    async def get_environment_builds(self, user: base_models.APIUser, environment_id: ULID) -> list[models.Build]:
        """Get all builds from a session environment."""

        # TODO: check READ permissions on this chain: environment->launcher->project
        # TODO: query DB based on environment_id

        async with self.session_maker() as session, session.begin():
            stmt = select(schemas.BuildORM).order_by(schemas.BuildORM.id.desc())
            result = await session.scalars(stmt)
            builds = result.all()

            # Check and refresh the status of in-progress builds
            for build in builds:
                await self._refresh_build(build=build, session=session)

            return [build.dump() for build in builds]

    async def insert_build(self, user: base_models.APIUser, build: models.UnsavedBuild) -> models.Build:
        """Insert a new build."""
        if not user.is_authenticated or user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")

        # TODO: check WRITE permissions on this chain: environment->launcher->project

        async with self.session_maker() as session, session.begin():
            build_orm = schemas.BuildORM(
                # environment_id=build.environment_id,
                status=models.BuildStatus.in_progress,
            )
            session.add(build_orm)
            await session.flush()
            await session.refresh(build_orm)

        result = build_orm.dump()

        # TODO: Get this from the session environment
        git_repository = "https://gitlab.dev.renku.ch/flora.thiebaut/python-simple.git"

        run_image = self.builds_config.vscodium_python_run_image or constants.BUILD_VSCODIUM_PYTHON_DEFAULT_RUN_IMAGE

        output_image_prefix = (
            self.builds_config.build_output_image_prefix or constants.BUILD_DEFAULT_OUTPUT_IMAGE_PREFIX
        )
        output_image_name = constants.BUILD_OUTPUT_IMAGE_NAME
        output_image_tag = result.get_k8s_name()
        output_image = f"{output_image_prefix}{output_image_name}{output_image_tag}"

        await shipwright_core.create_build(
            build=build_orm,
            git_repository=git_repository,
            run_image=run_image,
            output_image=output_image,
            shipwright_client=self.shipwright_client,
            builds_config=self.builds_config,
        )

        return result

    async def update_build(self, user: base_models.APIUser, build_id: ULID, patch: models.BuildPatch) -> models.Build:
        """Update a build entry."""
        if not user.is_authenticated or user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")

        # TODO: check WRITE permissions on this chain: build->environment->launcher->project

        async with self.session_maker() as session, session.begin():
            stmt = select(schemas.BuildORM).where(schemas.BuildORM.id == build_id)
            result = await session.scalars(stmt)
            build = result.one_or_none()

            if build is None:
                raise errors.MissingResourceError(
                    message=f"Build with id '{build_id}' does not exist or you do not have access to it."
                )

            # Check and refresh the status of in-progress builds
            await self._refresh_build(build=build, session=session)

            if build.status == models.BuildStatus.succeeded or build.status == models.BuildStatus.failed:
                raise errors.ValidationError(
                    message=f"Cannot update build with id '{build_id}': the build has status {build.status}."
                )

            # Only accept build cancellations
            if patch.status == models.BuildStatus.cancelled:
                build.status = patch.status

            await session.flush()
            await session.refresh(build)

        build_model = build.dump()

        await shipwright_core.cancel_build(build=build, shipwright_client=self.shipwright_client)

        return build_model

    async def _refresh_build(self, build: schemas.BuildORM, session: AsyncSession) -> None:
        if build.status != models.BuildStatus.in_progress:
            return

        await shipwright_core.update_build_status(build=build, shipwright_client=self.shipwright_client)

        await session.flush()
        await session.refresh(build)
