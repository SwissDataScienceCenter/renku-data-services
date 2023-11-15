"""Adapters for storage database classes."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.storage import models
from renku_data_services.storage import orm as schemas


class _Base:
    """Base class for repositories."""

    def __init__(self, engine: AsyncEngine, debug: bool = False):
        self.engine = engine
        self.session_maker = async_sessionmaker(self.engine, expire_on_commit=False)  # type: ignore[call-overload]


class StorageRepository(_Base):
    """Repository for cloud storage."""

    def __init__(
        self,
        gitlab_client: base_models.GitlabAPIProtocol,
        engine: AsyncEngine,
        debug: bool = False,
    ):
        super().__init__(engine, debug)
        self.gitlab_client = gitlab_client

    async def get_storage(
        self,
        user: base_models.APIUser,
        id: str | None = None,
        project_id: str | None = None,
        name: str | None = None,
    ) -> list[models.CloudStorage]:
        """Get a storage from the database."""
        async with self.session_maker() as session:
            stmt = select(schemas.CloudStorageORM)

            if project_id is not None:
                stmt = stmt.where(schemas.CloudStorageORM.project_id == project_id)
            if id is not None:
                stmt = stmt.where(schemas.CloudStorageORM.storage_id == id)

            if name is not None:
                stmt = stmt.where(schemas.CloudStorageORM.name == name)
            if not project_id and not name and not id:
                raise errors.ValidationError(
                    message="One of 'project_id', 'id' or 'name' has to be set when getting storage"
                )

            res = await session.execute(stmt)
            orms = res.scalars().all()
            accessible_projects = await self.gitlab_client.filter_projects_by_access_level(
                user, [p.project_id for p in orms], base_models.GitlabAccessLevel.MEMBER
            )

            return [p.dump() for p in orms if p.project_id in accessible_projects]

    async def get_storage_by_id(self, storage_id: str, user: base_models.APIUser) -> models.CloudStorage:
        """Get a single storage by id."""
        async with self.session_maker() as session:
            res = await session.execute(
                select(schemas.CloudStorageORM).where(schemas.CloudStorageORM.storage_id == storage_id)
            )
            storage = res.one_or_none()

            if storage is None:
                raise errors.MissingResourceError(message=f"The storage with id '{storage_id}' cannot be found")
            if not await self.gitlab_client.filter_projects_by_access_level(
                user, [storage[0].project_id], base_models.GitlabAccessLevel.MEMBER
            ):
                raise errors.Unauthorized(message="User does not have access to this project")
            return storage[0].dump()

    async def insert_storage(self, storage: models.CloudStorage, user: base_models.APIUser) -> models.CloudStorage:
        """Insert a new cloud storage entry."""
        if not await self.gitlab_client.filter_projects_by_access_level(
            user, [storage.project_id], base_models.GitlabAccessLevel.ADMIN
        ):
            raise errors.Unauthorized(message="User does not have access to this project")
        existing_storage = await self.get_storage(user, project_id=storage.project_id, name=storage.name)
        if existing_storage:
            raise errors.ValidationError(
                message=f"A storage with name {storage.name} already exists for project {storage.project_id}"
            )
        orm = schemas.CloudStorageORM.load(storage)
        async with self.session_maker() as session:
            async with session.begin():
                session.add(orm)
        return orm.dump()

    async def update_storage(self, storage_id: str, user: base_models.APIUser, **kwargs) -> models.CloudStorage:
        """Update a cloud storage entry."""
        async with self.session_maker() as session:
            async with session.begin():
                res = await session.execute(
                    select(schemas.CloudStorageORM).where(schemas.CloudStorageORM.storage_id == storage_id)
                )
                storage = res.scalars().one_or_none()

                if storage is None:
                    raise errors.MissingResourceError(message=f"The storage with id '{storage_id}' cannot be found")
                if not await self.gitlab_client.filter_projects_by_access_level(
                    user, [storage.project_id], base_models.GitlabAccessLevel.ADMIN
                ):
                    raise errors.Unauthorized(message="User does not have access to this project")
                if "project_id" in kwargs and kwargs["project_id"] != storage.project_id:
                    raise errors.ValidationError(message="Cannot change project id of existing storage.")
                name = kwargs.get("name", storage.name)
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

    async def delete_storage(self, storage_id: str, user: base_models.APIUser) -> None:
        """Delete a cloud storage entry."""
        async with self.session_maker() as session:
            async with session.begin():
                res = await session.execute(
                    select(schemas.CloudStorageORM).where(schemas.CloudStorageORM.storage_id == storage_id)
                )
                storage = res.one_or_none()

                if storage is None:
                    return
                if not await self.gitlab_client.filter_projects_by_access_level(
                    user, [storage[0].project_id], base_models.GitlabAccessLevel.ADMIN
                ):
                    raise errors.Unauthorized(message="User does not have access to this project")

                await session.delete(storage[0])
