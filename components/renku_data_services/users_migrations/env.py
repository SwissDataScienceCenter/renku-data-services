"""Alembic setup and environment used for database migrations."""
from renku_data_services.migrations.utils import run_migrations
from renku_data_services.users.orm import BaseORM

target_metadata = BaseORM.metadata
run_migrations([target_metadata])
