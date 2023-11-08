"""Custom migrations env file to support modular migrations."""
import os

from alembic import context
from sqlalchemy import MetaData, create_engine
from sqlalchemy.schema import CreateSchema

from renku_data_services.errors import errors


def include_object_factory(schema: str):
    """Filter only objects for the current database schema to be included."""

    def _include_object(object, name, type_, reflected, compare_to):
        if type_ == "table" and object.schema != schema:
            return False
        else:
            return True

    return _include_object


def run_migrations_offline(target_metadata, sync_sqlalchemy_url: str) -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    engine = create_engine(sync_sqlalchemy_url, pool_size=2, max_overflow=0)
    with engine.begin() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            literal_binds=True,
            dialect_opts={"paramstyle": "named"},
        )

        with context.begin_transaction():
            context.run_migrations()

    engine.dispose()


def run_migrations_online(target_metadata, sync_sqlalchemy_url: str) -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    engine = create_engine(sync_sqlalchemy_url, pool_size=2, max_overflow=0)
    with engine.begin() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_schema=target_metadata.schema,
            include_schemas=True,
            include_object=include_object_factory(target_metadata.schema),
        )

        connection.execute(CreateSchema(target_metadata.schema, if_not_exists=True))

        with context.begin_transaction():
            context.run_migrations()

    engine.dispose()


def run_migrations(metadata: MetaData):
    """Run migrations for a specific base model class."""
    # this is the Alembic Config object, which provides
    # access to the values within the .ini file in use.
    pg_host = os.environ.get("DB_HOST", "localhost")
    pg_user = os.environ.get("DB_USER", "renku")
    pg_port = os.environ.get("DB_PORT", "5432")
    db_name = os.environ.get("DB_NAME", "renku")
    pg_password = os.environ.get("DB_PASSWORD")
    if pg_password is None:
        raise errors.ConfigurationError(
            message="Please provide a database password in the 'DB_PASSWORD' environment variable."
        )
    sync_sqlalchemy_url = f"postgresql+psycopg://{pg_user}:{pg_password}@{pg_host}:{pg_port}/{db_name}"

    if context.is_offline_mode():
        run_migrations_offline(metadata, sync_sqlalchemy_url)
    else:
        run_migrations_online(metadata, sync_sqlalchemy_url)
