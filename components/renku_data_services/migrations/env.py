"""Custom migrations env file to support modular migrations."""
from logging.config import fileConfig
from typing import cast

from alembic import context
from alembic.config import Config
from renku_data_services.migrations.core import DataRepository
from sqlalchemy import MetaData


def run_migrations_offline(target_metadata, config: Config) -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    with cast(DataRepository, config.attributes.get("repo")).sync_engine.begin() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            literal_binds=True,
            dialect_opts={"paramstyle": "named"},
        )

        with context.begin_transaction():
            context.run_migrations()


def run_migrations_online(target_metadata, config: Config) -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    with cast(DataRepository, config.attributes.get("repo")).sync_engine.begin() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


def run_migrations(metadata: MetaData):
    """Run migrations for a specific base model class."""
    # this is the Alembic Config object, which provides
    # access to the values within the .ini file in use.
    config = context.config

    # Interpret the config file for Python logging.
    # This line sets up loggers basically.
    if config.config_file_name is not None:
        fileConfig(config.config_file_name)

    if context.is_offline_mode():
        run_migrations_offline(metadata, config)
    else:
        run_migrations_online(metadata, config)
