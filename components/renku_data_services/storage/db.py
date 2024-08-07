"""Adapters for storage database classes."""

from collections.abc import Callable
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.authz import models as authz_models
from renku_data_services.authz.authz import Authz, ResourceType
from renku_data_services.storage import models
from renku_data_services.storage import orm as schemas


class _Base:
    """Base class for repositories."""

    def __init__(self, session_maker: Callable[..., AsyncSession]) -> None:
        self.session_maker = session_maker


class BaseStorageRepository(_Base):
    """Base repository for cloud storage."""

    def __init__(
        self,
        session_maker: Callable[..., AsyncSession],
    ) -> None:
        super().__init__(session_maker)

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
    ) -> list[models.CloudStorage]:
        """Get a storage from the database."""
        async with self.session_maker() as session:
            stmt = select(schemas.CloudStorageORM)

            if project_id is not None:
                stmt = stmt.where(schemas.CloudStorageORM.project_id == str(project_id))
            if id is not None:
                stmt = stmt.where(schemas.CloudStorageORM.storage_id == (id))

            if name is not None:
                stmt = stmt.where(schemas.CloudStorageORM.name == name)
            if not project_id and not name and not id:
                raise errors.ValidationError(
                    message="One of 'project_id', 'id' or 'name' has to be set when getting storage"
                )

            res = await session.execute(stmt)
            orms = res.scalars().all()
            accessible_projects = await self.filter_projects_by_access_level(
                user, [p.project_id for p in orms], authz_models.Role.VIEWER
            )

            return [p.dump() for p in orms if p.project_id in accessible_projects]

    async def get_storage_by_id(self, storage_id: ULID, user: base_models.APIUser) -> models.CloudStorage:
        """Get a single storage by id."""
        async with self.session_maker() as session:
            storage = await session.scalar(
                select(schemas.CloudStorageORM).where(schemas.CloudStorageORM.storage_id == str(storage_id))
            )

            if storage is None:
                raise errors.MissingResourceError(message=f"The storage with id '{storage_id}' cannot be found")
            if not await self.filter_projects_by_access_level(user, [storage.project_id], authz_models.Role.VIEWER):
                raise errors.ForbiddenError(message="User does not have access to this project")
            return storage.dump()

    async def insert_storage(self, storage: models.CloudStorage, user: base_models.APIUser) -> models.CloudStorage:
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
                select(schemas.CloudStorageORM).where(schemas.CloudStorageORM.storage_id == str(storage_id))
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
                select(schemas.CloudStorageORM).where(schemas.CloudStorageORM.storage_id == str(storage_id))
            )
            storage = res.one_or_none()

            if storage is None:
                return
            if not await self.filter_projects_by_access_level(user, [storage[0].project_id], authz_models.Role.OWNER):
                raise errors.ForbiddenError(message="User does not have access to this project")

            await session.delete(storage[0])


class StorageRepository(BaseStorageRepository):
    """Repository for V1 cloud storage."""

    def __init__(
        self,
        gitlab_client: base_models.GitlabAPIProtocol,
        session_maker: Callable[..., AsyncSession],
    ) -> None:
        super().__init__(session_maker)
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
    ) -> None:
        super().__init__(session_maker)
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
            if await self.project_authz.has_permission(user, ResourceType.project, id, scope):
                output.append(id)
        return output
