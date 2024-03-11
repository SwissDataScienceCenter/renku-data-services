"""Custom migrations env file to support modular migrations."""
from typing import Sequence

from alembic import context
from sqlalchemy import Connection, MetaData, NullPool, create_engine
from sqlalchemy.schema import CreateSchema
from sqlalchemy.sql import text

from renku_data_services.db_config import DBConfig


def include_object(obj, name, type_, reflected, compare_to):
    if type_ == "table" and name == "alembic_version":
        return False
    return True


def combine_version_tables(conn: Connection, metadata_schema: str):
    """Used to combine all alembic version tables into one."""
    schemas = {
        # NOTE: These are the revisions that each schema will be when the version table is moved
        # in all other cases this function will do nothing.
        "authz": "748ed0f3439f",
        "projects": "7c08ed2fb79d",
        "resource_pools": "5403953f654f",
        "storage": "61a4d72981cf",
        "users": "3b30da432a76",
        "user_preferences": "6eccd7d4e3ed",
        "events": "4c425d8889b6",
    }
    rev = schemas.get(metadata_schema)
    if not rev:
        return
    version_table_exists_row = conn.execute(text(f"SELECT to_regclass('{metadata_schema}.alembic_version')")).fetchone()
    if not version_table_exists_row:
        return
    version_table_exists = version_table_exists_row[0]
    if not version_table_exists:
        return
    last_migration_row = conn.execute(text(f"SELECT version_num from {metadata_schema}.alembic_version")).fetchone()
    if not last_migration_row:
        return
    last_migration_rev = last_migration_row[0]
    if last_migration_rev != rev:
        return
    conn.execute(
        text(
            f"CREATE TABLE IF NOT EXISTS common.alembic_version (LIKE {metadata_schema}.alembic_version INCLUDING ALL)"
        )
    )
    conn.execute(text(f"INSERT INTO common.alembic_version(version_num) VALUES ('{rev}')"))
    conn.execute(text(f"DROP TABLE IF EXISTS {metadata_schema}.alembic_version"))


def run_migrations_offline(
    target_metadata: Sequence[MetaData], sync_sqlalchemy_url: str, version_table_schema: str | None = None
) -> None:
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
            include_object=include_object,
            version_table_schema=version_table_schema if version_table_schema else target_metadata[0].schema,
        )
        if version_table_schema is not None:
            conn.execute(CreateSchema(version_table_schema, if_not_exists=True))
        for m in target_metadata:
            conn.execute(CreateSchema(m.schema, if_not_exists=True))
            if version_table_schema == "common":
                combine_version_tables(conn, m.schema)

        with context.begin_transaction():
            context.run_migrations()


def run_migrations_online(
    target_metadata: Sequence[MetaData], sync_sqlalchemy_url: str, version_table_schema: str | None = None
) -> None:
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
            include_object=include_object,
            version_table_schema=version_table_schema if version_table_schema else target_metadata[0].schema,
        )
        if version_table_schema is not None:
            conn.execute(CreateSchema(version_table_schema, if_not_exists=True))
        for m in target_metadata:
            conn.execute(CreateSchema(m.schema, if_not_exists=True))
            if version_table_schema == "common":
                combine_version_tables(conn, m.schema)

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
