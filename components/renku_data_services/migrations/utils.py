"""Custom migrations env file to support modular migrations."""

from collections.abc import Sequence

from alembic import context
from sqlalchemy import Connection, MetaData, NullPool, create_engine
from sqlalchemy.schema import CreateSchema
from sqlalchemy.sql import text

from renku_data_services.db_config import DBConfig


def include_object(obj, name, type_, reflected, compare_to):
    """Prevents from alembic migrating the alembic_version tables."""
    if type_ == "table" and name == "alembic_version":
        return False
    return True


def combine_version_tables(conn: Connection, metadata_schema: str | None):
    """Used to combine all alembic version tables into one."""
    schemas = {
        # NOTE: These are the revisions that each schema will be when the version table is moved
        "authz": "748ed0f3439f",
        "projects": "7c08ed2fb79d",
        "resource_pools": "5403953f654f",
        "storage": "61a4d72981cf",
        "users": "3b30da432a76",
        "user_preferences": "6eccd7d4e3ed",
        "events": "4c425d8889b6",
    }
    if not metadata_schema:
        return
    with conn.begin_nested():
        rev = schemas.get(metadata_schema)
        if not rev:
            # The table revision is not the correct for merging version tables
            return
        version_table_exists_row = conn.execute(
            text(f"SELECT to_regclass('{metadata_schema}.alembic_version')")
        ).fetchone()
        if not version_table_exists_row:
            # The old version table or schema does not exist
            return
        version_table_exists = version_table_exists_row[0]
        if not version_table_exists:
            # The old version table or schema does not exist
            return
        last_migration_row = conn.execute(
            text(f"SELECT version_num from {metadata_schema}.alembic_version")  # nosec B608
        ).fetchone()
        if not last_migration_row:
            # The version table exists but it has not data
            return
        last_migration_rev = last_migration_row[0]
        if last_migration_rev != rev:
            # The version table has data but it does not match the revision required for migration
            return
        conn.execute(text(f"LOCK TABLE {metadata_schema}.alembic_version IN ACCESS EXCLUSIVE MODE"))
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS common.alembic_version "
                f"(LIKE {metadata_schema}.alembic_version INCLUDING ALL)"
            )
        )
        conn.execute(text("LOCK TABLE common.alembic_version IN ACCESS EXCLUSIVE MODE"))
        conn.execute(text("INSERT INTO common.alembic_version(version_num) VALUES (:rev)").bindparams(rev=rev))
        conn.execute(text(f"DROP TABLE IF EXISTS {metadata_schema}.alembic_version"))


def run_migrations_offline(target_metadata: Sequence[MetaData], sync_sqlalchemy_url: str) -> None:
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
            version_table_schema="common",
        )
        conn.execute(CreateSchema("common", if_not_exists=True))
        for m in target_metadata:
            conn.execute(CreateSchema(m.schema, if_not_exists=True))
            combine_version_tables(conn, m.schema)

        with context.begin_transaction():
            context.get_context()._ensure_version_table()
            conn.execute(text("LOCK TABLE common.alembic_version IN ACCESS EXCLUSIVE MODE"))
            context.run_migrations()


def run_migrations_online(target_metadata: Sequence[MetaData], sync_sqlalchemy_url: str) -> None:
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
            version_table_schema="common",
        )
        conn.execute(CreateSchema("common", if_not_exists=True))
        for m in target_metadata:
            conn.execute(CreateSchema(m.schema, if_not_exists=True))
            combine_version_tables(conn, m.schema)

        with context.begin_transaction():
            context.get_context()._ensure_version_table()
            conn.execute(text("LOCK TABLE common.alembic_version IN ACCESS EXCLUSIVE MODE"))
            context.run_migrations()


def run_migrations(metadata: Sequence[MetaData]):
    """Run migrations for a specific base model class."""
    # this is the Alembic Config object, which provides
    # access to the values within the .ini file in use.
    db_config = DBConfig.from_env()
    sync_sqlalchemy_url = db_config.conn_url(async_client=False)
    if context.is_offline_mode():
        run_migrations_offline(metadata, sync_sqlalchemy_url)
    else:
        run_migrations_online(metadata, sync_sqlalchemy_url)
