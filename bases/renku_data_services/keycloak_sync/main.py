"""Script to synchronize Keycloak and the user database."""

import asyncio
import logging

from renku_data_services.authz.admin_sync import sync_admins_from_keycloak
from renku_data_services.authz.authz import Authz
from renku_data_services.keycloak_sync.config import SyncConfig

logging.basicConfig(level=logging.INFO)


async def main() -> None:
    """Synchronize data from Keycloak and the user database."""
    config = SyncConfig.from_env()
    if config.total_user_sync:
        await config.syncer.users_sync(config.kc_api)
        await sync_admins_from_keycloak(config.kc_api, Authz(config.authz_config))
    else:
        await config.syncer.events_sync(config.kc_api)
        await sync_admins_from_keycloak(config.kc_api, Authz(config.authz_config))


if __name__ == "__main__":
    asyncio.run(main())
