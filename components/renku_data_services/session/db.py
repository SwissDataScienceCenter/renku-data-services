"""Adapters for session database classes."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager, nullcontext
from datetime import UTC, datetime

from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.authz.authz import Authz, ResourceType
from renku_data_services.authz.models import Scope
from renku_data_services.base_models.core import RESET
from renku_data_services.crc.db import ResourcePoolRepository
from renku_data_services.secrets import orm as secrets_schemas
from renku_data_services.secrets.core import encrypt_user_secret
from renku_data_services.secrets.models import SecretKind
from renku_data_services.session import models
from renku_data_services.session import orm as schemas
from renku_data_services.users.db import UserRepo


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
        if update.working_directory is not None:
            environment.working_directory = update.working_directory
        if update.mount_directory is not None:
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
                environment = environment_orm.dump()
                environment_id = environment.id
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
                environment = environment_orm.dump()

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


class SessionSecretRepository:
    """Repository for session secrets."""

    def __init__(
        self,
        session_maker: Callable[..., AsyncSession],
        project_authz: Authz,
        session_repo: SessionRepository,
        user_repo: UserRepo,
        secret_service_public_key: rsa.RSAPublicKey,
    ) -> None:
        self.session_maker = session_maker
        self.project_authz = project_authz
        self.session_repo = session_repo
        self.user_repo = user_repo
        self.secret_service_public_key = secret_service_public_key

    async def get_all_session_launcher_secret_slots_from_sesion_launcher(
        self,
        user: base_models.APIUser,
        session_launcher_id: ULID,
    ) -> list[models.SessionLauncherSecretSlot]:
        """Get all secret slots from a session launcher."""
        # Check that the user is allowed to access the session launcher
        await self.session_repo.get_launcher(user=user, launcher_id=session_launcher_id)
        async with self.session_maker() as session:
            result = await session.scalars(
                select(schemas.SessionLauncherSecretSlotORM).where(
                    schemas.SessionLauncherSecretSlotORM.session_launcher_id == session_launcher_id
                )
            )
            secret_slots = result.all()
            return [s.dump() for s in secret_slots]

    async def get_session_launcher_secret_slot(
        self,
        user: base_models.APIUser,
        slot_id: ULID,
    ) -> models.SessionLauncherSecretSlot:
        """Get one secret slot from the database."""
        async with self.session_maker() as session, session.begin():
            result = await session.scalars(
                select(schemas.SessionLauncherSecretSlotORM).where(schemas.SessionLauncherSecretSlotORM.id == slot_id)
            )
            secret_slot = result.one_or_none()

            authorized = (
                await self.project_authz.has_permission(
                    user, ResourceType.project, secret_slot.session_launcher.project_id, Scope.READ
                )
                if secret_slot is not None
                else False
            )
            if not authorized or secret_slot is None:
                raise errors.MissingResourceError(
                    message=f"Secret slot with id '{slot_id}' does not exist or you do not have access to it."
                )

            return secret_slot.dump()

    async def insert_session_launcher_secret_slot(
        self, user: base_models.APIUser, secret_slot: models.UnsavedSessionLauncherSecretSlot
    ) -> models.SessionLauncherSecretSlot:
        """Insert a new secret slot entry."""
        if user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")

        # Check that the user is allowed to access the session launcher
        await self.session_repo.get_launcher(user=user, launcher_id=secret_slot.session_launcher_id)
        async with self.session_maker() as session, session.begin():
            existing_secret_slot = await session.scalar(
                select(schemas.SessionLauncherSecretSlotORM)
                .where(schemas.SessionLauncherSecretSlotORM.session_launcher_id == secret_slot.session_launcher_id)
                .where(schemas.SessionLauncherSecretSlotORM.filename == secret_slot.filename)
            )
            if existing_secret_slot is not None:
                raise errors.ConflictError(
                    message=f"A secret slot with the filename '{secret_slot.filename}' already exists."
                )

            secret_slot_orm = schemas.SessionLauncherSecretSlotORM(
                session_launcher_id=secret_slot.session_launcher_id,
                name=secret_slot.name or secret_slot.filename,
                description=secret_slot.description if secret_slot.description else None,
                filename=secret_slot.filename,
                created_by_id=user.id,
            )

            session.add(secret_slot_orm)
            await session.flush()
            await session.refresh(secret_slot_orm)

            return secret_slot_orm.dump()

    async def update_session_launcher_secret_slot(
        self,
        user: base_models.APIUser,
        slot_id: ULID,
        patch: models.SessionLauncherSecretSlotPatch,
    ) -> models.SessionLauncherSecretSlot:
        """Update a secret slot entry."""
        not_found_msg = f"Secret slot with id '{slot_id}' does not exist or you do not have access to it."

        async with self.session_maker() as session, session.begin():
            result = await session.scalars(
                select(schemas.SessionLauncherSecretSlotORM).where(schemas.SessionLauncherSecretSlotORM.id == slot_id)
            )
            secret_slot = result.one_or_none()
            if secret_slot is None:
                raise errors.MissingResourceError(message=not_found_msg)

            authorized = await self.project_authz.has_permission(
                user, ResourceType.project, secret_slot.session_launcher.project_id, Scope.WRITE
            )
            if not authorized:
                raise errors.MissingResourceError(message=not_found_msg)

            if patch.name is not None:
                secret_slot.name = patch.name
            if patch.description is not None:
                secret_slot.description = patch.description if patch.description else None
            if patch.filename is not None:
                existing_secret_slot = await session.scalar(
                    select(schemas.SessionLauncherSecretSlotORM)
                    .where(schemas.SessionLauncherSecretSlotORM.session_launcher_id == secret_slot.session_launcher_id)
                    .where(schemas.SessionLauncherSecretSlotORM.filename == patch.filename)
                )
                if existing_secret_slot is not None:
                    raise errors.ConflictError(
                        message=f"A secret slot with the filename '{patch.filename}' already exists."
                    )
                secret_slot.filename = patch.filename

            await session.flush()
            await session.refresh(secret_slot)

            return secret_slot.dump()

    async def delete_session_launcher_secret_slot(
        self,
        user: base_models.APIUser,
        slot_id: ULID,
    ) -> None:
        """Delete a secret slot."""
        async with self.session_maker() as session, session.begin():
            result = await session.scalars(
                select(schemas.SessionLauncherSecretSlotORM).where(schemas.SessionLauncherSecretSlotORM.id == slot_id)
            )
            secret_slot = result.one_or_none()
            if secret_slot is None:
                return None

            authorized = await self.project_authz.has_permission(
                user, ResourceType.project, secret_slot.session_launcher.project_id, Scope.WRITE
            )
            if not authorized:
                raise errors.MissingResourceError(
                    message=f"Secret slot with id '{slot_id}' does not exist or you do not have access to it."
                )

            await session.delete(secret_slot)

    async def get_all_session_launcher_secrets_from_sesion_launcher(
        self,
        user: base_models.APIUser,
        session_launcher_id: ULID,
    ) -> list[models.SessionLauncherSecret]:
        """Get all secret from a session launcher."""
        if user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")

        # Check that the user is allowed to access the session launcher
        await self.session_repo.get_launcher(user=user, launcher_id=session_launcher_id)
        async with self.session_maker() as session:
            result = await session.scalars(
                select(schemas.SessionLauncherSecretORM)
                .where(schemas.SessionLauncherSecretORM.user_id == user.id)
                .where(schemas.SessionLauncherSecretORM.secret_slot_id == schemas.SessionLauncherSecretSlotORM.id)
                .where(schemas.SessionLauncherSecretSlotORM.session_launcher_id == session_launcher_id)
            )
            secrets = result.all()

            return [s.dump() for s in secrets]

    async def patch_session_launcher_secrets(
        self,
        user: base_models.APIUser,
        session_launcher_id: ULID,
        secrets: list[models.SessionSecretPatchExistingSecret | models.SessionSecretPatchSecretValue],
    ) -> list[models.SessionLauncherSecret]:
        """Create, update or remove session launcher secrets."""
        if user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")

        # Check that the user is allowed to access the session launcher
        await self.session_repo.get_launcher(user=user, launcher_id=session_launcher_id)

        secrets_as_dict = {s.secret_slot_id: s for s in secrets}

        async with self.session_maker() as session, session.begin():
            result = await session.scalars(
                select(schemas.SessionLauncherSecretORM)
                .where(schemas.SessionLauncherSecretORM.user_id == user.id)
                .where(schemas.SessionLauncherSecretORM.secret_slot_id == schemas.SessionLauncherSecretSlotORM.id)
                .where(schemas.SessionLauncherSecretSlotORM.session_launcher_id == session_launcher_id)
            )
            existing_secrets = result.all()
            existing_secrets_as_dict = {s.secret_slot_id: s for s in existing_secrets}

            result_slots = await session.scalars(
                select(schemas.SessionLauncherSecretSlotORM).where(
                    schemas.SessionLauncherSecretSlotORM.session_launcher_id == session_launcher_id
                )
            )
            secret_slots = result_slots.all()
            secret_slots_as_dict = {s.id: s for s in secret_slots}

            all_secrets = []

            for slot_id, secret_update in secrets_as_dict.items():
                secret_slot = secret_slots_as_dict.get(slot_id)
                if secret_slot is None:
                    raise errors.ValidationError(
                        message=f"Secret slot with id '{slot_id}' does not exist or you do not have access to it."
                    )

                if isinstance(secret_update, models.SessionSecretPatchExistingSecret):
                    # Update the secret_id
                    if session_launcher_secret_orm := existing_secrets_as_dict.get(slot_id):
                        session_launcher_secret_orm.secret_id = secret_update.secret_id
                    else:
                        session_launcher_secret_orm = schemas.SessionLauncherSecretORM(
                            secret_slot_id=secret_update.secret_slot_id,
                            secret_id=secret_update.secret_id,
                            user_id=user.id,
                        )
                    session.add(session_launcher_secret_orm)
                    all_secrets.append(session_launcher_secret_orm.dump())
                    continue

                if secret_update.value is None:
                    # Remove the secret
                    session_launcher_secret_orm = existing_secrets_as_dict.get(slot_id)
                    if session_launcher_secret_orm is None:
                        continue
                    await session.delete(session_launcher_secret_orm)
                    del existing_secrets_as_dict[slot_id]
                    continue

                encrypted_value, encrypted_key = await encrypt_user_secret(
                    user_repo=self.user_repo,
                    requested_by=user,
                    secret_service_public_key=self.secret_service_public_key,
                    secret_value=secret_update.value,
                )
                if session_launcher_secret_orm := existing_secrets_as_dict.get(slot_id):
                    session_launcher_secret_orm.secret.update(
                        encrypted_value=encrypted_value, encrypted_key=encrypted_key
                    )
                else:
                    secret_orm = secrets_schemas.SecretORM(
                        name=f"{secret_update.secret_slot_id}-{secret_slot.name}",
                        user_id=user.id,
                        encrypted_value=encrypted_value,
                        encrypted_key=encrypted_key,
                        kind=SecretKind.general,
                    )
                    session_launcher_secret_orm = schemas.SessionLauncherSecretORM(
                        secret_slot_id=secret_update.secret_slot_id,
                        secret_id=secret_orm.id,
                        user_id=user.id,
                    )
                    session.add(secret_orm)
                    session.add(session_launcher_secret_orm)
                    await session.flush()
                    await session.refresh(session_launcher_secret_orm)
                all_secrets.append(session_launcher_secret_orm.dump())

            return all_secrets

    async def delete_session_launcher_secrets(
        self,
        user: base_models.APIUser,
        session_launcher_id: ULID,
    ) -> None:
        """Delete data session launcher secrets."""
        if user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")

        async with self.session_maker() as session, session.begin():
            result = await session.scalars(
                select(schemas.SessionLauncherSecretORM)
                .where(schemas.SessionLauncherSecretORM.user_id == user.id)
                .where(schemas.SessionLauncherSecretORM.secret_slot_id == schemas.SessionLauncherSecretSlotORM.id)
                .where(schemas.SessionLauncherSecretSlotORM.session_launcher_id == session_launcher_id)
            )
            for secret in result:
                await session.delete(secret)
