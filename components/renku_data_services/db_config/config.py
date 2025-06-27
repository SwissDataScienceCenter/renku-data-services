"""DB Configuration."""

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import ClassVar

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from renku_data_services import errors


@dataclass
class DBConfig:
    """Database configuration."""

    password: str = field(repr=False)
    host: str = "localhost"
    user: str = "renku"
    port: str = "5432"
    db_name: str = "renku"
    _async_engine: ClassVar[AsyncEngine | None] = field(default=None, repr=False, init=False)
    pool_size: int = 10

    @classmethod
    def from_env(cls, pool_size: int = 10) -> "DBConfig":
        """Create a database configuration from environment variables."""

        pg_host = os.environ.get("DB_HOST")
        pg_user = os.environ.get("DB_USER")
        pg_port = os.environ.get("DB_PORT")
        db_name = os.environ.get("DB_NAME")
        pg_password = os.environ.get("DB_PASSWORD")
        if pg_password is None:
            raise errors.ConfigurationError(
                message="Please provide a database password in the 'DB_PASSWORD' environment variable."
            )
        config = cls(
            password=pg_password,
            host=pg_host or "localhost",
            user=pg_user or "renku",
            port=pg_port or "5432",
            db_name=db_name or "renku",
            pool_size=pool_size,
        )
        return config

    def conn_url(self, async_client: bool = True) -> str:
        """Return an asynchronous or synchronous database connection url."""
        if async_client:
            return f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.db_name}"
        return f"postgresql+psycopg://{self.user}:{self.password}@{self.host}:{self.port}/{self.db_name}"

    @property
    def async_session_maker(self) -> Callable[..., AsyncSession]:
        """The asynchronous DB engine."""
        if not DBConfig._async_engine:
            DBConfig._async_engine = create_async_engine(
                self.conn_url(),
                pool_size=self.pool_size,
                max_overflow=0,
            )
        return async_sessionmaker(DBConfig._async_engine, expire_on_commit=False)

    @staticmethod
    async def dispose_connection() -> None:
        """Dispose of the main database connection pool."""

        if DBConfig._async_engine:
            await DBConfig._async_engine.dispose()
            DBConfig._async_engine = None
