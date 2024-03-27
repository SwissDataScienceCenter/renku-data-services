"""Core alembic functionality."""

from pathlib import Path

from alembic import command, config
from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase, MappedAsDataclass


def run_migrations_for_app(name: str):
    """Perform migrations for app `name`.

    From: https://alembic.sqlalchemy.org/en/latest/cookbook.html#programmatic-api-use-connection-sharing-with-asyncio
    """

    alembic_ini_path = Path(__file__).resolve().parent / "alembic.ini"
    cfg = config.Config(alembic_ini_path, ini_section=name)
    command.upgrade(cfg, "heads")


class SecretBaseORM(MappedAsDataclass, DeclarativeBase):
    """Base class for all secret ORM classes."""

    metadata = MetaData(schema="secrets")
