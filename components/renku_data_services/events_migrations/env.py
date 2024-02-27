"""Alembic setup and environment used for database migrations."""
from renku_data_services.message_queue.orm import BaseORM
from renku_data_services.migrations.env import run_migrations

target_metadata = BaseORM.metadata
run_migrations(target_metadata)
