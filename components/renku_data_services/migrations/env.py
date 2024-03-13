"""Database migrations for Alembic."""

from renku_data_services.authz.orm import BaseORM as authz
from renku_data_services.crc.orm import BaseORM as crc
from renku_data_services.project.orm import BaseORM as project
from renku_data_services.storage.orm import BaseORM as storage
from renku_data_services.user_preferences.orm import BaseORM as user_preferences
from renku_data_services.users.orm import BaseORM as users
from renku_data_services.message_queue.orm import BaseORM as events
from renku_data_services.migrations.utils import run_migrations
from alembic import context
from logging.config import fileConfig

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
    storage.metadata,
    user_preferences.metadata,
    users.metadata,
    events.metadata,
]
run_migrations(all_metadata)
