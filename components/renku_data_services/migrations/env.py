"""Custom migrations env file to support modular migrations."""
from alembic import context
from sqlalchemy import MetaData, NullPool, create_engine
from sqlalchemy.schema import CreateSchema

from renku_data_services.config import DBConfig


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
    engine = create_engine(sync_sqlalchemy_url, poolclass=NullPool)
    with engine.connect() as conn:
        context.configure(
            connection=conn,
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
    engine = create_engine(sync_sqlalchemy_url, poolclass=NullPool)
    with engine.connect() as conn:
        context.configure(
            connection=conn,
            target_metadata=target_metadata,
            version_table_schema=target_metadata.schema,
            include_schemas=True,
            include_object=include_object_factory(target_metadata.schema),
        )

        conn.execute(CreateSchema(target_metadata.schema, if_not_exists=True))

        with context.begin_transaction():
            context.run_migrations()

    engine.dispose()


def run_migrations(metadata: MetaData):
    """Run migrations for a specific base model class."""
    # this is the Alembic Config object, which provides
    # access to the values within the .ini file in use.
    db_config = DBConfig.from_env()
    sync_sqlalchemy_url = db_config.conn_url(async_client=False)
    if context.is_offline_mode():
        run_migrations_offline(metadata, sync_sqlalchemy_url)
    else:
        run_migrations_online(metadata, sync_sqlalchemy_url)
