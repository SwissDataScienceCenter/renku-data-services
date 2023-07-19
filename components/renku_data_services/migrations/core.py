"""Core alembic functionality."""

from pathlib import Path
from alembic import command, config
from typing import Protocol
from sqlalchemy import Engine

from sqlalchemy.ext.asyncio import AsyncEngine


class DataRepository(Protocol):
    engine: AsyncEngine
    sync_engine: Engine


def run_migrations_for_app(name: str, repo: DataRepository):
    """Perform migrations for app `name`.

    From: https://alembic.sqlalchemy.org/en/latest/cookbook.html#programmatic-api-use-connection-sharing-with-asyncio  # noqa: E501
    """
    with repo.sync_engine.begin() as conn:
        alembic_ini_path = Path(__file__).resolve().parent / "alembic.ini"
        cfg = config.Config(alembic_ini_path, ini_section=name)
        cfg.attributes["connection"] = conn
        cfg.attributes["repo"] = repo
        command.upgrade(cfg, "head")
