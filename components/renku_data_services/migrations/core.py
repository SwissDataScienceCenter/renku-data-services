"""Core alembic functionality."""

from pathlib import Path

from alembic import command, config
from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase, MappedAsDataclass


def run_migrations_for_app(name: str):
    """Perform migrations for app `name`.

    From: https://alembic.sqlalchemy.org/en/latest/cookbook.html#programmatic-api-use-connection-sharing-with-asyncio
    """  # noqa: E501

    alembic_ini_path = Path(__file__).resolve().parent / "alembic.ini"
    cfg = config.Config(alembic_ini_path, ini_section=name)
    command.upgrade(cfg, "heads")


class AuthzBaseORM(MappedAsDataclass, DeclarativeBase):
    """Base class for all authz ORM classes."""

    metadata = MetaData(schema="authz")


class ResourcePoolBaseORM(MappedAsDataclass, DeclarativeBase):
    """Base class for all resource pool ORM classes."""

    metadata = MetaData(schema="resource_pools")


class EventsBaseORM(MappedAsDataclass, DeclarativeBase):
    """Base class for all resource pool ORM classes."""

    metadata = MetaData(schema="events")


class ProjectBaseORM(MappedAsDataclass, DeclarativeBase):
    """Base class for all project ORM classes."""

    metadata = MetaData(schema="projects")


class SessionBaseORM(MappedAsDataclass, DeclarativeBase):
    """Base class for all session ORM classes."""

    metadata = MetaData(schema="sessions")


class UserBaseORM(MappedAsDataclass, DeclarativeBase):
    """Base class for all users ORM classes."""

    metadata = MetaData(schema="users")


class UserPreferencesBaseORM(MappedAsDataclass, DeclarativeBase):
    """Base class for all user preferences ORM classes."""

    metadata = MetaData(schema="user_preferences")


class StorageBaseORM(MappedAsDataclass, DeclarativeBase):
    """Base class for all storage ORM classes."""

    metadata = MetaData(schema="storage")
