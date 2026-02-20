"""Custom migrations env file to support modular migrations."""

import asyncio
import threading
from asyncio.events import AbstractEventLoop
from collections.abc import Coroutine, Sequence
from typing import Any, Literal, TypeVar

from alembic import context
from sqlalchemy import Connection, MetaData, NullPool, create_engine
from sqlalchemy.schema import CreateSchema, SchemaItem
from sqlalchemy.sql import text

from renku_data_services.db_config import DBConfig
from renku_data_services.errors import errors


def include_object(
    obj: SchemaItem,
    name: str | None,
    type_: Literal[
        "schema",
        "table",
        "column",
        "index",
        "unique_constraint",
        "foreign_key_constraint",
    ],
    reflected: bool,
    compare_to: SchemaItem | None,
) -> bool:
    """Prevents from alembic migrating the alembic_version tables."""
    return type_ != "table" or (name != "alembic_version" and name != "resource_requests_view")


def combine_version_tables(conn: Connection, metadata_schema: str | None) -> None:
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
            if not m.schema:
                raise errors.ConfigurationError(
                    message=f"Cannot run migrations because the schema name for tables {m.tables.values()} is missing"
                )
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
            if not m.schema:
                raise errors.ConfigurationError(
                    message=f"Cannot run migrations because the schema name for tables {m.tables.values()} is missing"
                )
            conn.execute(CreateSchema(m.schema, if_not_exists=True))
            combine_version_tables(conn, m.schema)

        with context.begin_transaction():
            context.get_context()._ensure_version_table()
            conn.execute(text("LOCK TABLE common.alembic_version IN ACCESS EXCLUSIVE MODE"))
            context.run_migrations()


def run_migrations(metadata: Sequence[MetaData]) -> None:
    """Run migrations for a specific base model class."""
    # this is the Alembic Config object, which provides
    # access to the values within the .ini file in use.
    db_config = DBConfig.from_env()
    sync_sqlalchemy_url = db_config.conn_url(async_client=False)
    if context.is_offline_mode():
        run_migrations_offline(metadata, sync_sqlalchemy_url)
    else:
        run_migrations_online(metadata, sync_sqlalchemy_url)


_T = TypeVar("_T")


def _run_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    asyncio.set_event_loop(loop)
    loop.run_forever()


def _prepare_event_loop() -> tuple[AbstractEventLoop, threading.Thread]:
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=_run_event_loop, args=(loop,), daemon=True)
    thread.start()
    return loop, thread


class UtilityEventLoop:
    """Allows you to run a coroutine in a synchronous way by utilizing a separate event loop in a separate thread."""

    _loop, _thread = _prepare_event_loop()

    @classmethod
    def run(cls, coro: Coroutine[Any, Any, _T]) -> _T:
        """Executes the specific coroutine in a separate thread with its own event loop.

        Note that this will block until the coroutine completes. Async/await should be used if you have the chance.
        """
        future = asyncio.run_coroutine_threadsafe(coro, cls._loop)
        return future.result()

    def __del__(self) -> None:
        self._loop.stop()
        self._loop.close()
        self._thread.join()
        del self._loop
        del self._thread
