"""Script to run a variety of background jobs independently from the data services deployment."""

import argparse
import asyncio
import logging

from renku_data_services.authz.admin_sync import sync_admins_from_keycloak
from renku_data_services.authz.authz import Authz
from renku_data_services.background_jobs.config import SyncConfig
from renku_data_services.background_jobs.core import (
    bootstrap_user_namespaces,
    fix_mismatched_project_namespace_ids,
    migrate_groups_make_all_public,
    migrate_storages_v2_to_data_connectors,
    migrate_user_namespaces_make_all_public,
)
from renku_data_services.background_jobs.utils import ErrorHandler
from renku_data_services.migrations.core import run_migrations_for_app

logging.basicConfig(level=logging.INFO)


async def short_period_sync() -> None:
    """Perform synchronizations and jobs that should occur more often."""
    config = SyncConfig.from_env()
    run_migrations_for_app("common")

    error_handler = ErrorHandler()

    async with error_handler:
        await bootstrap_user_namespaces(config)
    async with error_handler:
        await config.syncer.events_sync(config.kc_api)
    async with error_handler:
        await sync_admins_from_keycloak(config.kc_api, Authz(config.authz_config))
    async with error_handler:
        await fix_mismatched_project_namespace_ids(config)
    async with error_handler:
        await migrate_groups_make_all_public(config)
    async with error_handler:
        await migrate_user_namespaces_make_all_public(config)
    async with error_handler:
        await migrate_storages_v2_to_data_connectors(config)

    error_handler.maybe_raise()


async def long_period_sync() -> None:
    """Perform synchronizations and jobs that can occur more rarely."""
    config = SyncConfig.from_env()
    run_migrations_for_app("common")
    error_handler = ErrorHandler()

    async with error_handler:
        await config.syncer.users_sync(config.kc_api)
    async with error_handler:
        await sync_admins_from_keycloak(config.kc_api, Authz(config.authz_config))

    error_handler.maybe_raise()


async def main() -> None:
    """Synchronize data from Keycloak and the user database."""
    logger = logging.getLogger("background_jobs")
    logger.setLevel(logging.INFO)

    parser = argparse.ArgumentParser(prog="Data Service Background Jobs")
    subparsers = parser.add_subparsers(help="Background job to run")

    short_period_sync_parser = subparsers.add_parser(
        "short_period_sync", help="Perform background jobs that need to occur more often"
    )
    short_period_sync_parser.set_defaults(func=short_period_sync)
    long_period_sync_parser = subparsers.add_parser(
        "long_period_sync", help="Perform background jobs that need to occur at a longer period"
    )
    long_period_sync_parser.set_defaults(func=long_period_sync)

    args = parser.parse_args()
    await args.func()


if __name__ == "__main__":
    asyncio.run(main())
