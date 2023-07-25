"""Adapters for storage database classes."""

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker


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

    pass  # TODO: implement
