"""Adapters for storage database classes."""

from collections.abc import Callable
from typing import cast

from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from ulid import ULID

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.authz import models as authz_models
from renku_data_services.authz.authz import Authz, ResourceType
from renku_data_services.secrets import orm as secrets_schemas
from renku_data_services.secrets.core import encrypt_user_secret
from renku_data_services.secrets.models import SecretKind
from renku_data_services.secrets.orm import SecretORM
from renku_data_services.storage import models
from renku_data_services.storage import orm as schemas
from renku_data_services.users.db import UserRepo


class _Base:
    """Base class for repositories."""

    def __init__(self, session_maker: Callable[..., AsyncSession]) -> None:
        self.session_maker = session_maker


class BaseStorageRepository(_Base):
    """Base repository for cloud storage."""

    def __init__(
        self,
        session_maker: Callable[..., AsyncSession],
        user_repo: UserRepo,
        secret_service_public_key: rsa.RSAPublicKey,
    ) -> None:
        super().__init__(session_maker)
        self.user_repo: UserRepo = user_repo
        self.secret_service_public_key: rsa.RSAPublicKey = secret_service_public_key

    async def filter_projects_by_access_level(
        self, user: base_models.APIUser, project_ids: list[str], minimum_access_level: authz_models.Role
    ) -> list[str]:
        """Get a list of projects of which the user is a member with a specific access level."""
        raise NotImplementedError

    async def get_storage(
        self,
        user: base_models.APIUser,
        id: str | None = None,
        project_id: str | ULID | None = None,
        name: str | None = None,
        include_secrets: bool = False,
        filter_by_access_level: bool = True,
    ) -> list[models.CloudStorage]:
        """Get a storage from the database."""
        async with self.session_maker() as session:
            if not project_id and not name and not id:
                raise errors.ValidationError(
                    message="One of 'project_id', 'id' or 'name' has to be set when getting storage"
                )

            stmt = select(schemas.CloudStorageORM)

            if project_id is not None:
                stmt = stmt.where(schemas.CloudStorageORM.project_id == project_id)
            if id is not None:
                stmt = stmt.where(schemas.CloudStorageORM.storage_id == id)
            if name is not None:
                stmt = stmt.where(schemas.CloudStorageORM.name == name)
            if include_secrets:
                stmt = stmt.options(
                    selectinload(
                        schemas.CloudStorageORM.secrets.and_(schemas.CloudStorageSecretsORM.user_id == user.id)
                    )
                )

            res = await session.execute(stmt)
            storage_orms = res.scalars().all()

            if not filter_by_access_level:
                return [s.dump() for s in storage_orms]

            accessible_projects = await self.filter_projects_by_access_level(
                user, [s.project_id for s in storage_orms], authz_models.Role.VIEWER
            )

            return [s.dump() for s in storage_orms if s.project_id in accessible_projects]

    async def get_storage_by_id(self, storage_id: ULID, user: base_models.APIUser) -> models.CloudStorage:
        """Get a single storage by id."""
        storages = await self.get_storage(user, id=str(storage_id), include_secrets=True, filter_by_access_level=False)

        if not storages:
            raise errors.MissingResourceError(message=f"The storage with id '{storage_id}' cannot be found")
        if not await self.filter_projects_by_access_level(user, [storages[0].project_id], authz_models.Role.VIEWER):
            raise errors.ForbiddenError(message="User does not have access to this project")

        return storages[0]

    async def insert_storage(
        self, storage: models.UnsavedCloudStorage, user: base_models.APIUser
    ) -> models.CloudStorage:
        """Insert a new cloud storage entry."""
        if not await self.filter_projects_by_access_level(user, [storage.project_id], authz_models.Role.OWNER):
            raise errors.ForbiddenError(message="User does not have access to this project")
        existing_storage = await self.get_storage(user, project_id=storage.project_id, name=storage.name)
        if existing_storage:
            raise errors.ValidationError(
                message=f"A storage with name {storage.name} already exists for project {storage.project_id}"
            )
        orm = schemas.CloudStorageORM.load(storage)
        async with self.session_maker() as session, session.begin():
            session.add(orm)
        return orm.dump()

    async def update_storage(self, storage_id: ULID, user: base_models.APIUser, **kwargs: dict) -> models.CloudStorage:
        """Update a cloud storage entry."""
        async with self.session_maker() as session, session.begin():
            res = await session.execute(
                select(schemas.CloudStorageORM).where(schemas.CloudStorageORM.storage_id == storage_id)
            )
            storage = res.scalars().one_or_none()

            if storage is None:
                raise errors.MissingResourceError(message=f"The storage with id '{storage_id}' cannot be found")
            if not await self.filter_projects_by_access_level(user, [storage.project_id], authz_models.Role.OWNER):
                raise errors.ForbiddenError(message="User does not have access to this project")
            if "project_id" in kwargs and cast(str, kwargs.get("project_id")) != storage.project_id:
                raise errors.ValidationError(message="Cannot change project id of existing storage.")
            name = cast(str, kwargs.get("name", storage.name))
            if storage.name != name:
                existing_storage = await self.get_storage(user, project_id=storage.project_id, name=name)
                if existing_storage:
                    raise errors.ValidationError(
                        message=f"A storage with name {storage.name} already exists for project "
                        f"{storage.project_id}"
                    )

            for key, value in kwargs.items():
                setattr(storage, key, value)

            if "configuration" in kwargs and "type" in kwargs["configuration"]:
                storage.storage_type = kwargs["configuration"]["type"]

            result = storage.dump()  # triggers validation before the transaction saves data

        return result

    async def delete_storage(self, storage_id: ULID, user: base_models.APIUser) -> None:
        """Delete a cloud storage entry."""
        async with self.session_maker() as session, session.begin():
            res = await session.execute(
                select(schemas.CloudStorageORM).where(schemas.CloudStorageORM.storage_id == storage_id)
            )
            storage = res.one_or_none()

            if storage is None:
                return
            if not await self.filter_projects_by_access_level(user, [storage[0].project_id], authz_models.Role.OWNER):
                raise errors.ForbiddenError(message="User does not have access to this project")

            await session.delete(storage[0])

    async def upsert_storage_secrets(
        self, storage_id: ULID, user: base_models.APIUser, secrets: list[models.CloudStorageSecretUpsert]
    ) -> list[models.CloudStorageSecret]:
        """Create/update cloud storage secrets."""
        # NOTE: Check that user has proper access to the storage
        storage = await self.get_storage_by_id(storage_id=storage_id, user=user)

        secret_names_values = {s.name: s.value for s in secrets}
        async with self.session_maker() as session, session.begin():
            stmt = (
                select(schemas.CloudStorageSecretsORM)
                .where(schemas.CloudStorageSecretsORM.user_id == user.id)
                .where(schemas.CloudStorageSecretsORM.storage_id == storage.storage_id)
                .options(selectinload(schemas.CloudStorageSecretsORM.secret))
            )
            result = await session.execute(stmt)
            existing_storage_secrets_orm = result.scalars().all()

            existing_secrets = {s.name: s for s in existing_storage_secrets_orm}
            stored_secrets = []

            for name, value in secret_names_values.items():
                encrypted_value, encrypted_key = await encrypt_user_secret(
                    user_repo=self.user_repo,
                    requested_by=user,
                    secret_service_public_key=self.secret_service_public_key,
                    secret_value=value,
                )

                if storage_secret_orm := existing_secrets.get(name):
                    storage_secret_orm.secret.update(encrypted_value=encrypted_value, encrypted_key=encrypted_key)
                else:
                    secret_orm = secrets_schemas.SecretORM(
                        name=f"{storage_id}-{name}",
                        user_id=cast(str, user.id),
                        encrypted_value=encrypted_value,
                        encrypted_key=encrypted_key,
                        kind=SecretKind.storage,
                    )
                    session.add(secret_orm)

                    storage_secret_orm = schemas.CloudStorageSecretsORM(
                        user_id=cast(str, user.id),
                        storage_id=storage_id,
                        name=name,
                        secret_id=secret_orm.id,
                    )
                    session.add(storage_secret_orm)

                stored_secrets.append(storage_secret_orm.dump())

            return stored_secrets

    async def get_storage_secrets(self, storage_id: ULID, user: base_models.APIUser) -> list[models.CloudStorageSecret]:
        """Get cloud storage secrets."""
        async with self.session_maker() as session, session.begin():
            stmt = (
                select(schemas.CloudStorageSecretsORM)
                .where(schemas.CloudStorageSecretsORM.user_id == user.id)
                .where(schemas.CloudStorageSecretsORM.storage_id == storage_id)
            )
            result = await session.execute(stmt)
            storage_secrets_orm = result.scalars().all()

            return [s.dump() for s in storage_secrets_orm]

    async def delete_storage_secrets(self, storage_id: ULID, user: base_models.APIUser) -> None:
        """Delete cloud storage secrets."""
        async with self.session_maker() as session, session.begin():
            stmt = (
                delete(SecretORM)
                .where(schemas.CloudStorageSecretsORM.secret_id == SecretORM.id)
                .where(schemas.CloudStorageSecretsORM.user_id == user.id)
                .where(schemas.CloudStorageSecretsORM.storage_id == storage_id)
            )
            await session.execute(stmt)
            stmt = (
                delete(schemas.CloudStorageSecretsORM)
                .where(schemas.CloudStorageSecretsORM.user_id == user.id)
                .where(schemas.CloudStorageSecretsORM.storage_id == storage_id)
            )
            await session.execute(stmt)


class StorageRepository(BaseStorageRepository):
    """Repository for V1 cloud storage."""

    def __init__(
        self,
        gitlab_client: base_models.GitlabAPIProtocol,
        session_maker: Callable[..., AsyncSession],
        user_repo: UserRepo,
        secret_service_public_key: rsa.RSAPublicKey,
    ) -> None:
        super().__init__(session_maker, user_repo, secret_service_public_key)
        self.gitlab_client = gitlab_client

    async def filter_projects_by_access_level(
        self, user: base_models.APIUser, project_ids: list[str], minimum_access_level: authz_models.Role
    ) -> list[str]:
        """Get a list of Gitlab project IDs of which the user is a member with a specific access level."""
        gitlab_access_level = (
            base_models.GitlabAccessLevel.ADMIN
            if minimum_access_level == authz_models.Role.OWNER
            else base_models.GitlabAccessLevel.MEMBER
        )

        return await self.gitlab_client.filter_projects_by_access_level(user, project_ids, gitlab_access_level)


class StorageV2Repository(BaseStorageRepository):
    """Repository for V2 cloud storage."""

    def __init__(
        self,
        project_authz: Authz,
        session_maker: Callable[..., AsyncSession],
        user_repo: UserRepo,
        secret_service_public_key: rsa.RSAPublicKey,
    ) -> None:
        super().__init__(session_maker, user_repo, secret_service_public_key)
        self.project_authz: Authz = project_authz

    async def filter_projects_by_access_level(
        self, user: base_models.APIUser, project_ids: list[str], minimum_access_level: authz_models.Role
    ) -> list[str]:
        """Get a list of project IDs of which the user is a member with a specific access level."""
        if not user.is_authenticated or not project_ids:
            return []

        scope = authz_models.Scope.WRITE if minimum_access_level == authz_models.Role.OWNER else authz_models.Scope.READ
        output = []
        for id in project_ids:
            if await self.project_authz.has_permission(user, ResourceType.project, ULID.from_str(id), scope):
                output.append(id)
        return output
