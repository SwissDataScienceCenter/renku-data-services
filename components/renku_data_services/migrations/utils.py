"""Custom migrations env file to support modular migrations."""
from alembic import context
from sqlalchemy import MetaData, NullPool, create_engine
from sqlalchemy.schema import CreateSchema

from renku_data_services.db_config import DBConfig


def include_object_factory(schema: str):
    """Filter only objects for the current database schema to be included."""

    def _include_object(object, name, type_, reflected, compare_to):
        if type_ == "table" and object.schema != schema:
            return False
        else:
            return True

    return _include_object


def run_migrations_offline(target_metadata, sync_sqlalchemy_url: str, version_table_schema: str | None = None) -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    engine = create_engine(sync_sqlalchemy_url, poolclass=NullPool)
    with engine.connect() as conn:
        context.configure(
            connection=conn,
            target_metadata=target_metadata,
            literal_binds=True,
            dialect_opts={"paramstyle": "named"},
            include_schemas=True,
            version_table_schema=version_table_schema if version_table_schema else target_metadata.schema,
        )
        conn.execute(CreateSchema(target_metadata.schema, if_not_exists=True))

        with context.begin_transaction():
            context.run_migrations()


def run_migrations_online(target_metadata, sync_sqlalchemy_url: str, version_table_schema: str | None = None) -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    engine = create_engine(sync_sqlalchemy_url, poolclass=NullPool)
    with engine.connect() as conn:
        context.configure(
            connection=conn,
            target_metadata=target_metadata,
            include_schemas=True,
            version_table_schema=version_table_schema if version_table_schema else target_metadata.schema,
        )
        conn.execute(CreateSchema(target_metadata.schema, if_not_exists=True))

        with context.begin_transaction():
            context.run_migrations()


def run_migrations(metadata: MetaData, version_table_schema: str | None = None):
    """Run migrations for a specific base model class."""
    # this is the Alembic Config object, which provides
    # access to the values within the .ini file in use.
    db_config = DBConfig.from_env()
    sync_sqlalchemy_url = db_config.conn_url(async_client=False)
    if context.is_offline_mode():
        run_migrations_offline(metadata, sync_sqlalchemy_url, version_table_schema)
    else:
        run_migrations_online(metadata, sync_sqlalchemy_url, version_table_schema)
