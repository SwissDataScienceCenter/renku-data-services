"""Database migrations for Alembic."""

from logging.config import fileConfig

from alembic import context
from secret_storage.secret.orm import BaseORM as secrets

from renku_data_services.migrations.utils import run_migrations

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

all_metadata = [
    secrets.metadata,
]
schemas = {
    # NOTE: These are the revisions that each schema will be when the version table is moved
    "secrets": "62935e3d8520"
}

run_migrations(schemas=schemas, metadata=all_metadata)
