"""DB Configuration."""

import asyncio
import os
from dataclasses import dataclass, field
from typing import Callable, ClassVar

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

    @classmethod
    def from_env(cls, prefix: str = ""):
        """Create a database configuration from environment variables."""

        pg_host = os.environ.get(f"{prefix}DB_HOST")
        pg_user = os.environ.get(f"{prefix}DB_USER")
        pg_port = os.environ.get(f"{prefix}DB_PORT")
        db_name = os.environ.get(f"{prefix}DB_NAME")
        pg_password = os.environ.get(f"{prefix}DB_PASSWORD")
        if pg_password is None:
            raise errors.ConfigurationError(
                message=f"Please provide a database password in the '{prefix}DB_PASSWORD' environment variable."
            )
        kwargs = {"host": pg_host, "password": pg_password, "port": pg_port, "db_name": db_name, "user": pg_user}
        return cls(**{k: v for (k, v) in kwargs.items() if v is not None})

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
                pool_size=10,
                max_overflow=0,
            )
        return async_sessionmaker(DBConfig._async_engine, expire_on_commit=False)

    @staticmethod
    def dispose_connection():
        """Dispose of the main database connection pool."""

        if DBConfig._async_engine:
            asyncio.get_event_loop().run_until_complete(DBConfig._async_engine.dispose())
