"""Adapters for storage database classes."""

from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import renku_data_services.storage_models as models
from renku_data_services import errors
from renku_data_services.storage_adapters import schemas


class _Base:
    """Base class for repositories."""

    def __init__(self, sync_sqlalchemy_url: str, async_sqlalchemy_url: str, debug: bool = False):
        self.engine = create_async_engine(async_sqlalchemy_url, echo=debug)
        self.sync_engine = create_engine(sync_sqlalchemy_url, echo=debug)
        self.session_maker = sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )  # type: ignore[call-overload]


class StorageRepository(_Base):
    """Repository for cloud storage."""

    async def get_storage(self, id: str | None = None, project_id: str | None = None) -> list[models.CloudStorage]:
        """Get a storage from the database."""
        async with self.session_maker() as session:
            stmt = select(schemas.CloudStorageORM)

            if project_id is not None:
                stmt = stmt.where(schemas.CloudStorageORM.project_id == project_id)
            if id is not None:
                stmt = stmt.where(schemas.CloudStorageORM.storage_id == id)

            res = await session.execute(stmt)
            orms = res.scalars().all()
            return [orm.dump() for orm in orms]

    async def get_storage_by_id(self, storage_id: str) -> models.CloudStorage:
        """Get a single storage by id."""
        async with self.session_maker() as session:
            res = await session.execute(
                select(schemas.CloudStorageORM).where(schemas.CloudStorageORM.storage_id == storage_id)
            )
            storage = res.one_or_none()

            if storage is None:
                raise errors.MissingResourceError(message=f"The storage with id '{storage_id}' cannot be found")
            return storage[0].dump()

    async def insert_storage(self, storage: models.CloudStorage) -> models.CloudStorage:
        """Insert a new cloud storage entry."""
        orm = schemas.CloudStorageORM.load(storage)
        async with self.session_maker() as session:
            async with session.begin():
                session.add(orm)
        return orm.dump()

    async def update_storage(self, storage_id: str, **kwargs) -> models.CloudStorage:
        """Update a cloud storage entry."""
        async with self.session_maker() as session:
            async with session.begin():
                res = await session.execute(
                    select(schemas.CloudStorageORM).where(schemas.CloudStorageORM.storage_id == storage_id)
                )
                storage = res.one_or_none()

                if storage is None:
                    raise errors.MissingResourceError(message=f"The storage with id '{storage_id}' cannot be found")
                storage = storage[0]

                for key, value in kwargs.items():
                    setattr(storage, key, value)

                if "configuration" in kwargs and "type" in kwargs["configuration"]:
                    storage.storage_type = kwargs["configuration"]["type"]

                result = storage.dump()  # triggers validation before the transaction saves data

        return result

    async def delete_storage(self, storage_id: str) -> None:
        """Delete a cloud storage entry."""
        async with self.session_maker() as session:
            async with session.begin():
                res = await session.execute(
                    select(schemas.CloudStorageORM).where(schemas.CloudStorageORM.storage_id == storage_id)
                )
                storage = res.one_or_none()

                if storage is None:
                    return

                await session.delete(storage[0])
