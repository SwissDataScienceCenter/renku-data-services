"""Script to synchronize Keycloak and the user database."""
import asyncio
import logging

from renku_data_services.keycloak_sync.config import SyncConfig
from renku_data_services.migrations.core import run_migrations_for_app

logging.basicConfig(level=logging.INFO)


async def main():
    """Synchronize data from Keycloak and the user database."""
    config = SyncConfig.from_env()
    run_migrations_for_app("common", "users")
    if config.total_user_sync:
        await config.syncer.users_sync(config.kc_api)
    else:
        await config.syncer.events_sync(config.kc_api)


if __name__ == "__main__":
    asyncio.run(main())
