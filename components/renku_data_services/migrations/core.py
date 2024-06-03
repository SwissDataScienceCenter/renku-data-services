"""Core alembic functionality."""

from pathlib import Path

from alembic import command, config


def get_alembic_config(name: str):
    """Returns the Alembic configuration for app `name`."""
    alembic_ini_path = Path(__file__).resolve().parent / "alembic.ini"
    return config.Config(alembic_ini_path, ini_section=name)


def run_migrations_for_app(name: str, revision: str = "heads") -> None:
    """Perform migrations for app `name`.

    From: https://alembic.sqlalchemy.org/en/latest/cookbook.html#programmatic-api-use-connection-sharing-with-asyncio
    """  # noqa: E501
    cfg = get_alembic_config(name)
    command.upgrade(cfg, revision)
