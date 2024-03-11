"""Core alembic functionality."""

from pathlib import Path

from alembic import command, config


def run_migrations_for_app(name: str, branch: str | None = None):
    """Perform migrations for app `name`, and optionally for a specific alembic branch.

    If the branch is ommitted or set to None then the migration will be executed for all alembic branches.
    From: https://alembic.sqlalchemy.org/en/latest/cookbook.html#programmatic-api-use-connection-sharing-with-asyncio  # noqa: E501
    """

    alembic_ini_path = Path(__file__).resolve().parent / "alembic.ini"
    cfg = config.Config(alembic_ini_path, ini_section=name)
    if branch:
        command.upgrade(cfg, f"{branch}@head")
    else:
        command.upgrade(cfg, "heads")
