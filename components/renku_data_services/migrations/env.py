"""Database migrations for Alembic."""

from logging.config import fileConfig

from alembic import context

from renku_data_services.authz.orm import BaseORM as authz
from renku_data_services.crc.orm import BaseORM as crc
from renku_data_services.message_queue.orm import BaseORM as events
from renku_data_services.migrations.utils import run_migrations
from renku_data_services.project.orm import BaseORM as project
from renku_data_services.session.orm import BaseORM as sessions
from renku_data_services.storage.orm import BaseORM as storage
from renku_data_services.user_preferences.orm import BaseORM as user_preferences
from renku_data_services.users.orm import BaseORM as users

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

all_metadata = [
    authz.metadata,
    crc.metadata,
    project.metadata,
    sessions.metadata,
    storage.metadata,
    user_preferences.metadata,
    users.metadata,
    events.metadata,
]
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

run_migrations(schemas=schemas, metadata=all_metadata)
