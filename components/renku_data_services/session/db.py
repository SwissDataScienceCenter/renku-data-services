"""Adapters for session database classes."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager, nullcontext
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.app_config import logging
from renku_data_services.authz.authz import Authz, ResourceType
from renku_data_services.authz.models import Scope
from renku_data_services.base_models.core import RESET
from renku_data_services.crc.db import ResourcePoolRepository
from renku_data_services.session import constants, models
from renku_data_services.session import orm as schemas
from renku_data_services.session.k8s_client import ShipwrightClient

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from renku_data_services.session.config import BuildsConfig


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
            environment_image_source=new_environment.environment_image_source,
            command=new_environment.command,
            args=new_environment.args,
            creation_date=datetime.now(UTC).replace(microsecond=0),
            is_archived=new_environment.is_archived,
            strip_path_prefix=new_environment.strip_path_prefix,
        )

        session.add(environment)
        return environment

    def __copy_environment(
        self,
        user: base_models.APIUser,
        session: AsyncSession,
        environment: models.Environment,
    ) -> schemas.EnvironmentORM:
        if user.id is None:
            raise errors.UnauthorizedError(
                message="You have to be authenticated to insert an environment in the DB.", quiet=True
            )
        new_environment = schemas.EnvironmentORM(
            name=environment.name,
            created_by_id=user.id,
            description=environment.description,
            container_image=environment.container_image,
            default_url=environment.default_url,
            port=environment.port,
            working_directory=environment.working_directory,
            mount_directory=environment.mount_directory,
            uid=environment.uid,
            gid=environment.gid,
            environment_kind=environment.environment_kind,
            command=environment.command,
            args=environment.args,
            creation_date=datetime.now(UTC).replace(microsecond=0),
            is_archived=environment.is_archived,
            environment_image_source=environment.environment_image_source,
            strip_path_prefix=environment.strip_path_prefix,
        )

        if environment.environment_image_source == models.EnvironmentImageSource.build:
            if not environment.build_parameters:
                raise errors.ProgrammingError(message="Environment has no build parameters.")
            platforms = [
                schemas.BuildPlatformORM(platform=platform) for platform in environment.build_parameters.platforms
            ]
            new_build_parameters = schemas.BuildParametersORM(
                platforms=platforms,
                builder_variant=environment.build_parameters.builder_variant,
                frontend_variant=environment.build_parameters.frontend_variant,
                repository=environment.build_parameters.repository,
                repository_revision=environment.build_parameters.repository_revision,
                context_dir=environment.build_parameters.context_dir,
            )
            session.add(new_build_parameters)

            new_environment.build_parameters_id = new_build_parameters.id
            new_environment.build_parameters = new_build_parameters

        session.add(new_environment)
        return new_environment

    def __insert_build_parameters_environment(
        self,
        user: base_models.APIUser,
        session: AsyncSession,
        launcher: schemas.SessionLauncherORM,
        new_build_parameters_environment: models.UnsavedBuildParameters,
    ) -> schemas.EnvironmentORM:
        if user.id is None:
            raise errors.UnauthorizedError(
                message="You have to be authenticated to insert an environment in the DB.", quiet=True
            )
        platforms = [
            schemas.BuildPlatformORM(platform=platform) for platform in new_build_parameters_environment.platforms
        ]
        build_parameters_orm = schemas.BuildParametersORM(
            platforms=platforms,
            builder_variant=new_build_parameters_environment.builder_variant,
            frontend_variant=new_build_parameters_environment.frontend_variant,
            repository=new_build_parameters_environment.repository,
            repository_revision=new_build_parameters_environment.repository_revision,
            context_dir=new_build_parameters_environment.context_dir,
        )
        session.add(build_parameters_orm)

        environment_orm = schemas.EnvironmentORM(
            name=launcher.name,
            created_by_id=user.id,
            description=f"Generated environment for {launcher.name}",
            container_image="image:unknown-at-the-moment",  # TODO: This should come from the build
            default_url="/lab",  # TODO: This should come from the build
            port=8888,  # TODO: This should come from the build
            working_directory=None,  # TODO: This should come from the build
            mount_directory=None,  # TODO: This should come from the build
            uid=1000,  # TODO: This should come from the build
            gid=1000,  # TODO: This should come from the build
            environment_kind=models.EnvironmentKind.CUSTOM,
            command=None,  # TODO: This should come from the build
            args=None,  # TODO: This should come from the build
            creation_date=datetime.now(UTC).replace(microsecond=0),
            environment_image_source=models.EnvironmentImageSource.build,
            build_parameters_id=build_parameters_orm.id,
            build_parameters=build_parameters_orm,
            strip_path_prefix=False,
        )
        session.add(environment_orm)
        return environment_orm

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
        if update.strip_path_prefix is not None:
            environment.strip_path_prefix = update.strip_path_prefix

    async def __update_environment_build_parameters(
        self, environment: schemas.EnvironmentORM, update: models.EnvironmentPatch
    ) -> None:
        # TODO: For now, we don't allow updating other fields of a session environment
        if not update.build_parameters:
            return

        build_parameters = update.build_parameters

        if build_parameters.repository is not None:
            environment.build_parameters.repository = build_parameters.repository
        if build_parameters.platforms is not None:
            environment.build_parameters.platforms = [
                schemas.BuildPlatformORM(platform=platform) for platform in build_parameters.platforms
            ]
        if build_parameters.builder_variant is not None:
            environment.build_parameters.builder_variant = build_parameters.builder_variant
        if build_parameters.frontend_variant is not None:
            environment.build_parameters.frontend_variant = build_parameters.frontend_variant
        if build_parameters.repository_revision == "":
            environment.build_parameters.repository_revision = None
        elif build_parameters.repository_revision:
            environment.build_parameters.repository_revision = build_parameters.repository_revision
        if build_parameters.context_dir == "":
            environment.build_parameters.context_dir = None
        elif build_parameters.context_dir:
            environment.build_parameters.context_dir = build_parameters.context_dir

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

        start_build = False

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
                    environment_image_source=models.EnvironmentImageSource.image,
                    strip_path_prefix=launcher.environment.strip_path_prefix,
                )
                session.add(environment_orm)
            elif isinstance(launcher.environment, models.UnsavedBuildParameters):
                platforms = [schemas.BuildPlatformORM(platform=platform) for platform in launcher.environment.platforms]
                build_parameters_orm = schemas.BuildParametersORM(
                    platforms=platforms,
                    builder_variant=launcher.environment.builder_variant,
                    frontend_variant=launcher.environment.frontend_variant,
                    repository=launcher.environment.repository,
                    repository_revision=launcher.environment.repository_revision,
                    context_dir=launcher.environment.context_dir,
                )
                session.add(build_parameters_orm)

                environment_orm = schemas.EnvironmentORM(
                    name=launcher.name,
                    created_by_id=user.id,
                    description=f"Generated environment for {launcher.name}",
                    container_image="image:unknown-at-the-moment",  # TODO: This should come from the build
                    default_url=constants.BUILD_URL_PATH_MAP.get(
                        launcher.environment.frontend_variant, constants.BUILD_DEFAULT_URL_PATH
                    ),
                    port=constants.BUILD_PORT,  # TODO: This should come from the build
                    working_directory=constants.BUILD_WORKING_DIRECTORY,  # TODO: This should come from the build
                    mount_directory=constants.BUILD_MOUNT_DIRECTORY,  # TODO: This should come from the build
                    uid=constants.BUILD_UID,  # TODO: This should come from the build
                    gid=constants.BUILD_GID,  # TODO: This should come from the build
                    environment_kind=models.EnvironmentKind.CUSTOM,
                    command=None,  # TODO: This should come from the build
                    args=None,  # TODO: This should come from the build
                    creation_date=datetime.now(UTC).replace(microsecond=0),
                    environment_image_source=models.EnvironmentImageSource.build,
                    build_parameters_id=build_parameters_orm.id,
                    build_parameters=build_parameters_orm,
                    strip_path_prefix=False,  # TODO: Should this maybe be adjustable?
                )
                session.add(environment_orm)

                start_build = True
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
                env_variables=models.EnvVar.to_dict(launcher.env_variables) if launcher.env_variables else None,
                created_by_id=user.id,
                creation_date=datetime.now(UTC).replace(microsecond=0),
            )
            session.add(launcher_orm)
            await session.flush()
            await session.refresh(launcher_orm)

        if start_build:
            build = models.UnsavedBuild(environment_id=environment_id)
            await self.start_build(user, build)

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

            if launcher.environment.environment_kind == models.EnvironmentKind.CUSTOM:
                environment = self.__copy_environment(user, session, launcher.environment)
                environment_id = environment.id
            else:
                environment_id = launcher.environment.id

            launcher_orm = schemas.SessionLauncherORM(
                name=launcher.name,
                project_id=project_id,
                description=launcher.description,
                environment_id=environment_id,
                resource_class_id=launcher.resource_class_id,
                disk_storage=launcher.disk_storage,
                env_variables=models.EnvVar.to_dict(launcher.env_variables) if launcher.env_variables else None,
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
                    message=f"Session launcher with id '{launcher_id}' does not exist or you do not have access to it."
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
            if isinstance(patch.env_variables, list):
                launcher.env_variables = models.EnvVar.to_dict(patch.env_variables)
            elif patch.env_variables is RESET:
                launcher.env_variables = None

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
        update: models.EnvironmentPatch | models.UnsavedEnvironment | models.UnsavedBuildParameters | str,
    ) -> None:
        current_env_kind = launcher.environment.environment_kind
        match update, current_env_kind:
            case str() as env_id, _:
                # The environment in the launcher is set via ID, the new ID has to refer
                # to an environment that is global.
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
                    # A custom environment exists, but it is being updated to a global one
                    # We remove the custom environment to avoid accumulating custom environments that are not associated
                    # with any launchers.
                    await session.delete(old_environment)
            case models.EnvironmentPatch(), models.EnvironmentKind.CUSTOM:
                # The custom environment is updated without changing the image source
                if launcher.environment.environment_image_source == models.EnvironmentImageSource.build:
                    await self.__update_environment_build_parameters(launcher.environment, update)
                else:
                    self.__update_environment(launcher.environment, update)
            case models.UnsavedEnvironment() as new_custom_environment, models.EnvironmentKind.GLOBAL:
                # Global environment replaced by a custom one
                new_env = self.__insert_environment(user, session, new_custom_environment)
                launcher.environment_id = new_env.id
                launcher.environment = new_env
                await session.flush()
            case models.UnsavedEnvironment() as new_custom_environment, models.EnvironmentKind.CUSTOM:
                # Custom environment with build is replaced by a custom environment with image
                build_parameters = launcher.environment.build_parameters

                launcher.environment.name = update.name
                launcher.environment.description = update.description
                launcher.environment.container_image = update.container_image
                launcher.environment.default_url = update.default_url
                launcher.environment.port = update.port
                launcher.environment.working_directory = update.working_directory
                launcher.environment.mount_directory = update.mount_directory
                launcher.environment.uid = update.uid
                launcher.environment.gid = update.gid
                launcher.environment.environment_kind = models.EnvironmentKind.CUSTOM
                launcher.environment.command = update.command
                launcher.environment.args = update.args
                launcher.environment.environment_image_source = models.EnvironmentImageSource.image
                launcher.environment.build_parameters_id = None
                launcher.environment.strip_path_prefix = update.strip_path_prefix

                # NOTE: Delete the build parameters since they are not used by any other environment
                await session.delete(build_parameters)

                await session.flush()
            case models.UnsavedBuildParameters() as new_custom_built_environment, models.EnvironmentKind.GLOBAL:
                # Global environment replaced by a custom one which will be built
                new_env = self.__insert_build_parameters_environment(
                    user, session, launcher, new_custom_built_environment
                )
                launcher.environment_id = new_env.id
                launcher.environment = new_env
                await session.flush()
            case models.UnsavedBuildParameters() as new_custom_built_environment, models.EnvironmentKind.CUSTOM:
                # Custom environment with image is replaced by a custom environment with build
                platforms = [
                    schemas.BuildPlatformORM(platform=platform) for platform in new_custom_built_environment.platforms
                ]
                build_parameters_orm = schemas.BuildParametersORM(
                    platforms=platforms,
                    builder_variant=new_custom_built_environment.builder_variant,
                    frontend_variant=new_custom_built_environment.frontend_variant,
                    repository=new_custom_built_environment.repository,
                    repository_revision=new_custom_built_environment.repository_revision,
                    context_dir=new_custom_built_environment.context_dir,
                )
                session.add(build_parameters_orm)

                launcher.environment.container_image = (
                    "image:unknown-at-the-moment"  # TODO: This should come from the build
                )
                launcher.environment.default_url = "/lab"  # TODO: This should come from the build
                launcher.environment.port = 8888  # TODO: This should come from the build
                launcher.environment.working_directory = None  # TODO: This should come from the build
                launcher.environment.mount_directory = None  # TODO: This should come from the build
                launcher.environment.uid = 1000  # TODO: This should come from the build
                launcher.environment.gid = 1000  # TODO: This should come from the build
                launcher.environment.environment_kind = models.EnvironmentKind.CUSTOM
                launcher.environment.command = None  # TODO: This should come from the build
                launcher.environment.args = None  # TODO: This should come from the build
                launcher.environment.environment_image_source = models.EnvironmentImageSource.build
                launcher.environment.build_parameters_id = build_parameters_orm.id
                launcher.environment.build_parameters = build_parameters_orm
                launcher.environment.strip_path_prefix = False

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
        async with self.session_maker() as session, session.begin():
            stmt = select(schemas.BuildORM).where(schemas.BuildORM.id == build_id)
            result = await session.scalars(stmt)
            build = result.one_or_none()

            not_found_message = f"Build with id '{build_id}' does not exist or you do not have access to it."
            if build is None:
                raise errors.MissingResourceError(message=not_found_message)

            authorized = await self._get_environment_authorization(
                session=session, user=user, environment=build.environment, scope=Scope.READ
            )
            if not authorized:
                raise errors.MissingResourceError(message=not_found_message)

            # Check and refresh the status of in-progress builds
            if user.id is not None:
                await self._refresh_build(build=build, session=session, user_id=user.id)

            return build.dump()

    async def get_environment_builds(self, user: base_models.APIUser, environment_id: ULID) -> list[models.Build]:
        """Get all builds from a session environment."""

        if not user.is_authenticated or user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")

        async with self.session_maker() as session, session.begin():
            environment = await session.scalar(
                select(schemas.EnvironmentORM).where(schemas.EnvironmentORM.id == environment_id)
            )

            not_found_message = (
                f"Session environment with id '{environment_id}' does not exist or you do not have access to it."
            )
            if environment is None:
                raise errors.MissingResourceError(message=not_found_message)

            authorized = await self._get_environment_authorization(
                session=session, user=user, environment=environment, scope=Scope.READ
            )
            if not authorized:
                raise errors.MissingResourceError(message=not_found_message)

            stmt = (
                select(schemas.BuildORM)
                .where(schemas.BuildORM.environment_id == environment_id)
                .order_by(schemas.BuildORM.id.desc())
            )
            result = await session.scalars(stmt)
            builds = result.all()

            # Check and refresh the status of in-progress builds
            for build in builds:
                await self._refresh_build(build=build, session=session, user_id=user.id)

            return [build.dump() for build in builds]

    async def start_build(self, user: base_models.APIUser, build: models.UnsavedBuild) -> models.Build:
        """Insert a new build."""
        if not user.is_authenticated or user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")

        async with self.session_maker() as session, session.begin():
            environment = await session.scalar(
                select(schemas.EnvironmentORM).where(schemas.EnvironmentORM.id == build.environment_id)
            )

            not_found_message = (
                f"Session environment with id '{build.environment_id}' does not exist or you do not have access to it."
            )
            if environment is None:
                raise errors.MissingResourceError(message=not_found_message)

            authorized = await self._get_environment_authorization(
                session=session, user=user, environment=environment, scope=Scope.READ
            )
            if not authorized:
                raise errors.MissingResourceError(message=not_found_message)

            if environment.environment_kind == models.EnvironmentKind.GLOBAL:
                launcher_orm = None
            else:
                launcher_orm = await session.scalar(
                    select(schemas.SessionLauncherORM).where(
                        schemas.SessionLauncherORM.environment_id == build.environment_id
                    )
                )

            build_parameters = environment.build_parameters.dump()

            # We check if there is any in-progress build
            in_progress_builds = await session.stream_scalars(
                select(schemas.BuildORM)
                .where(schemas.BuildORM.environment_id == build.environment_id)
                .where(schemas.BuildORM.status == models.BuildStatus.in_progress)
                .order_by(schemas.BuildORM.id.desc())
            )
            async for item in in_progress_builds:
                await self._refresh_build(build=item, session=session, user_id=user.id)
                if item.status == models.BuildStatus.in_progress:
                    raise errors.ConflictError(
                        message=f"Session environment with id '{build.environment_id}' already has a build in progress."
                    )

            # We check that we build for a single target platform
            if len(build_parameters.platforms) > 1:
                raise errors.CannotStartBuildError(
                    message=(
                        f"Building images can target only one platform at a time. "
                        f"Current value: {build_parameters.platforms}"
                    )
                )

            build_orm = schemas.BuildORM(
                environment_id=build.environment_id,
                status=models.BuildStatus.in_progress,
            )
            session.add(build_orm)
            await session.flush()
            await session.refresh(build_orm)

        result = build_orm.dump()
        launcher = launcher_orm.dump() if launcher_orm is not None else None

        if self.shipwright_client is not None:
            params = self._get_buildrun_params(
                user=user, build=result, build_parameters=build_parameters, launcher=launcher
            )
            await self.shipwright_client.create_image_build(params=params, user_id=user.id)
        else:
            logger.error("Shipwright client is None")

        return result

    async def update_build(self, user: base_models.APIUser, build_id: ULID, patch: models.BuildPatch) -> models.Build:
        """Update a build entry."""
        if not user.is_authenticated or user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")

        async with self.session_maker() as session, session.begin():
            stmt = select(schemas.BuildORM).where(schemas.BuildORM.id == build_id)
            result = await session.scalars(stmt)
            build = result.one_or_none()

            not_found_message = f"Build with id '{build_id}' does not exist or you do not have access to it."
            if build is None:
                raise errors.MissingResourceError(message=not_found_message)

            authorized = await self._get_environment_authorization(
                session=session, user=user, environment=build.environment, scope=Scope.WRITE
            )
            if not authorized:
                raise errors.MissingResourceError(message=not_found_message)

            # Check and refresh the status of in-progress builds
            await self._refresh_build(build=build, session=session, user_id=user.id)

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

        if self.shipwright_client is not None:
            await self.shipwright_client.cancel_build_run(name=build_model.k8s_name, user_id=user.id)
        else:
            logger.error("Shipwright client is None")

        return build_model

    async def get_build_logs(
        self, user: base_models.APIUser, build_id: ULID, max_log_lines: int | None = None
    ) -> dict[str, str]:
        """Get the logs of a build by querying Shipwright."""
        if not user.is_authenticated or user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")

        async with self.session_maker() as session, session.begin():
            stmt = select(schemas.BuildORM).where(schemas.BuildORM.id == build_id)
            result = await session.scalars(stmt)
            build = result.one_or_none()

            if build is None:
                raise errors.MissingResourceError(
                    message=f"Build with id '{build_id}' does not exist or you do not have access to it."
                )

            if build.environment.environment_kind == models.EnvironmentKind.GLOBAL:
                authorized = True
            else:
                launcher = await session.scalar(
                    select(schemas.SessionLauncherORM).where(
                        schemas.SessionLauncherORM.environment_id == build.environment_id
                    )
                )
                if launcher is None:
                    authorized = False
                else:
                    authorized = await self.project_authz.has_permission(
                        user, ResourceType.project, launcher.project_id, Scope.WRITE
                    )
            if not authorized:
                raise errors.MissingResourceError(
                    message=f"Build with id '{build_id}' does not exist or you do not have access to it."
                )

        build_model = build.dump()

        if self.shipwright_client is None:
            raise errors.MissingResourceError(message=f"Build with id '{build_id}' does not have logs.")

        return await self.shipwright_client.get_image_build_logs(
            buildrun_name=build_model.k8s_name, user_id=user.id, max_log_lines=max_log_lines
        )

    async def _refresh_build(self, build: schemas.BuildORM, session: AsyncSession, user_id: str) -> None:
        """Refresh the status of a build by querying Shipwright."""
        if build.status != models.BuildStatus.in_progress:
            return

        # Note: We can't get an update about the build if there is no client for Shipwright.
        if self.shipwright_client is None:
            logger.error("Shipwright client is None")
            return

        # TODO: consider how we can parallelize calls to `shipwright_client` for refreshes.
        status_update = await self.shipwright_client.update_image_build_status(
            buildrun_name=build.dump().k8s_name, user_id=user_id
        )

        if status_update.update is None:
            return

        update = status_update.update
        if update is not None and update.status == models.BuildStatus.failed:
            build.status = models.BuildStatus.failed
            build.completed_at = update.completed_at
            build.error_reason = update.error_reason
        elif update is not None and update.status == models.BuildStatus.succeeded and update.result is not None:
            build.status = models.BuildStatus.succeeded
            build.completed_at = update.completed_at
            build.result_image = update.result.image
            build.result_repository_url = update.result.repository_url
            build.result_repository_git_commit_sha = update.result.repository_git_commit_sha
            # Also update the session environment here
            # TODO: move this to its own method where build parameters determine args
            environment = build.environment
            environment.container_image = build.result_image
            # An older version was hardcoding the values but we can and should
            # rely on the defaults for args and command
            if environment.command is not None:
                environment.command = None
            if environment.args is not None:
                environment.args = None

        await session.flush()
        await session.refresh(build)

    def _get_buildrun_params(
        self,
        user: base_models.APIUser,
        build: models.Build,
        build_parameters: models.BuildParameters,
        launcher: models.SessionLauncher | None,
    ) -> models.ShipwrightBuildRunParams:
        """Derive the Shipwright BuildRun params from a Build instance and a BuildParameters instance."""
        if not user.is_authenticated or user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")

        git_repository = build_parameters.repository
        git_repository_revision = build_parameters.repository_revision
        context_dir = build_parameters.context_dir

        builder_image = self.builds_config.build_builder_image or constants.BUILD_DEFAULT_BUILDER_IMAGE
        run_image = self.builds_config.build_run_image or constants.BUILD_DEFAULT_RUN_IMAGE

        output_image_prefix = (
            self.builds_config.build_output_image_prefix or constants.BUILD_DEFAULT_OUTPUT_IMAGE_PREFIX
        )
        output_image_name = constants.BUILD_OUTPUT_IMAGE_NAME
        output_image_tag = build.k8s_name
        output_image = f"{output_image_prefix}{output_image_name}:{output_image_tag}"

        # TODO: define the build strategy from `build_parameters`
        build_strategy_name = self.builds_config.build_strategy_name or constants.BUILD_DEFAULT_BUILD_STRATEGY_NAME
        push_secret_name = self.builds_config.push_secret_name or constants.BUILD_DEFAULT_PUSH_SECRET_NAME

        node_selector = self.builds_config.node_selector
        tolerations = self.builds_config.tolerations

        retention_after_failed = (
            self.builds_config.buildrun_retention_after_failed or constants.BUILD_RUN_DEFAULT_RETENTION_AFTER_FAILED
        )
        retention_after_succeeded = (
            self.builds_config.buildrun_retention_after_succeeded
            or constants.BUILD_RUN_DEFAULT_RETENTION_AFTER_SUCCEEDED
        )
        build_timeout = self.builds_config.buildrun_build_timeout or constants.BUILD_RUN_DEFAULT_TIMEOUT

        labels: dict[str, str] = {
            "renku.io/safe-username": user.id,
        }
        annotations: dict[str, str] = {
            "renku.io/build_id": str(build.id),
            "renku.io/environment_id": str(build.environment_id),
        }
        if launcher:
            annotations["renku.io/launcher_id"] = str(launcher.id)
            annotations["renku.io/project_id"] = str(launcher.project_id)

        params = models.ShipwrightBuildRunParams(
            name=build.k8s_name,
            git_repository=git_repository,
            builder_image=builder_image,
            run_image=run_image,
            output_image=output_image,
            build_strategy_name=build_strategy_name,
            push_secret_name=push_secret_name,
            retention_after_failed=retention_after_failed,
            retention_after_succeeded=retention_after_succeeded,
            build_timeout=build_timeout,
            node_selector=node_selector,
            tolerations=tolerations,
            labels=labels,
            annotations=annotations,
            frontend=build_parameters.frontend_variant,
            git_repository_revision=git_repository_revision,
            context_dir=context_dir,
        )

        platform = models.Platform.linux_amd64
        if build_parameters.platforms:
            platform = build_parameters.platforms[0]
        overrides = None
        if self.builds_config.build_platform_overrides:
            overrides = self.builds_config.build_platform_overrides.get(platform.value)
        params = params.with_overrides(overrides=overrides)

        return params

    async def _get_environment_authorization(
        self, session: AsyncSession, user: base_models.APIUser, environment: schemas.EnvironmentORM, scope: Scope
    ) -> bool:
        """Checks whether the provided user has a specific permission on a session environment."""
        if environment.environment_kind == models.EnvironmentKind.GLOBAL:
            return scope == Scope.READ or user.is_admin

        launcher = await session.scalar(
            select(schemas.SessionLauncherORM).where(schemas.SessionLauncherORM.environment_id == environment.id)
        )
        authorized = False
        if launcher:
            authorized = await self.project_authz.has_permission(user, ResourceType.project, launcher.project_id, scope)
        return authorized
