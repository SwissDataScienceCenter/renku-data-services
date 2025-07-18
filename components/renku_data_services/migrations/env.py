"""Database migrations for Alembic."""

from renku_data_services.authz.orm import BaseORM as authz
from renku_data_services.connected_services.orm import BaseORM as connected_services
from renku_data_services.crc.orm import BaseORM as crc
from renku_data_services.data_connectors.orm import BaseORM as data_connectors
from renku_data_services.k8s_watcher import BaseORM as k8s_cache
from renku_data_services.message_queue.orm import BaseORM as events
from renku_data_services.metrics.orm import BaseORM as metrics
from renku_data_services.migrations.utils import run_migrations
from renku_data_services.namespace.orm import BaseORM as namespaces
from renku_data_services.platform.orm import BaseORM as platform
from renku_data_services.project.orm import BaseORM as project
from renku_data_services.search.orm import BaseORM as search
from renku_data_services.secrets.orm import BaseORM as secrets
from renku_data_services.session.orm import BaseORM as sessions
from renku_data_services.storage.orm import BaseORM as storage
from renku_data_services.users.orm import BaseORM as users

all_metadata = [
    authz.metadata,
    crc.metadata,
    connected_services.metadata,
    data_connectors.metadata,
    events.metadata,
    k8s_cache.metadata,
    metrics.metadata,
    namespaces.metadata,
    platform.metadata,
    project.metadata,
    secrets.metadata,
    sessions.metadata,
    storage.metadata,
    users.metadata,
    search.metadata,
]

run_migrations(all_metadata)
