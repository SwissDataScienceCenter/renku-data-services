from renku_data_services.authz.orm import BaseORM as authz
from renku_data_services.crc.orm import BaseORM as crc
from renku_data_services.project.orm import BaseORM as project
from renku_data_services.storage.orm import BaseORM as storage
from renku_data_services.user_preferences.orm import BaseORM as user_preferences
from renku_data_services.users.orm import BaseORM as users
from renku_data_services.migrations.utils import run_migrations

run_migrations(authz.metadata, "common")
run_migrations(crc.metadata, "common")
run_migrations(project.metadata, "common")
run_migrations(storage.metadata, "common")
run_migrations(user_preferences.metadata, "common")
run_migrations(users.metadata, "common")
