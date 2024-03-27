"""DB Configuration."""

import asyncio
from dataclasses import dataclass, field
from typing import Callable, ClassVar

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from renku_data_services.db_config import DBConfig as DataServiceDBConfig


@dataclass
class SecretStorageDBConfig(DataServiceDBConfig):
    """Database configuration."""

    _async_engine: ClassVar[AsyncEngine | None] = field(default=None, repr=False, init=False)

    @property
    def async_session_maker(self) -> Callable[..., AsyncSession]:
        """The asynchronous DB engine."""
        if not SecretStorageDBConfig._async_engine:
            SecretStorageDBConfig._async_engine = create_async_engine(
                self.conn_url(),
                pool_size=10,
                max_overflow=0,
            )
        return async_sessionmaker(SecretStorageDBConfig._async_engine, expire_on_commit=False)

    @staticmethod
    def dispose_connection():
        """Dispose of the main database connection pool."""

        if SecretStorageDBConfig._async_engine:
            asyncio.get_event_loop().run_until_complete(SecretStorageDBConfig._async_engine.dispose())
