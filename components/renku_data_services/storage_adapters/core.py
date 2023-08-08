"""Adapters for storage database classes."""

from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import renku_data_services.storage_models as models
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

    async def get_storage(self, id: str | None = None, git_url: str | None = None) -> list[models.CloudStorage]:
        """Get a storage from the database."""
        async with self.session_maker() as session:
            stmt = select(schemas.CloudStorageORM)

            if git_url is not None:
                stmt = stmt.where(schemas.CloudStorageORM.git_url == git_url)
            if id is not None:
                stmt = stmt.where(schemas.CloudStorageORM.storage_id == id)

            res = await session.execute(stmt)
            orms = res.scalars().all()
            return [orm.dump() for orm in orms]

    async def insert_storage(self, storage: models.CloudStorage) -> models.CloudStorage:
        """Insert a new cloud storage entry."""
        orm = schemas.CloudStorageORM.load(storage)
        async with self.session_maker() as session:
            async with session.begin():
                session.add(orm)
        return orm.dump()
