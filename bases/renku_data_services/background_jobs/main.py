"""Script to run a variety of background jobs independently from the data services deployment."""

import argparse
import asyncio
import logging

from renku_data_services.authz.admin_sync import sync_admins_from_keycloak
from renku_data_services.authz.authz import Authz
from renku_data_services.background_jobs.config import SyncConfig
from renku_data_services.background_jobs.utils import bootstrap_user_namespaces
from renku_data_services.migrations.core import run_migrations_for_app

logging.basicConfig(level=logging.INFO)


async def main() -> None:
    """Synchronize data from Keycloak and the user database."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "tasks",
        nargs="+",
        choices=["keycloak_events_sync", "keycloak_users_sync", "keycloak_admins_sync", "user_namespaces_bootstrap"],
    )
    config = SyncConfig.from_env()
    args = parser.parse_args()
    for task in args.tasks:
        logging.info(f"Starting task {task}")
        match task:
            case "keycloak_events_sync":
                await config.syncer.events_sync(config.kc_api)
            case "keycloak_users_sync":
                await config.syncer.users_sync(config.kc_api)
            case "keycloak_admins_sync":
                await sync_admins_from_keycloak(config.kc_api, Authz(config.authz_config))
            case "user_namespaces_bootstrap":
                run_migrations_for_app("common")
                await bootstrap_user_namespaces(config)
            case _:
                raise ValueError(f"Found an unexpected background job task name '{task}'")


if __name__ == "__main__":
    asyncio.run(main())
