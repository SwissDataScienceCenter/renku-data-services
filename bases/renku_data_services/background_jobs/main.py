"""Script to synchronize Keycloak and the user database."""

import argparse
import asyncio
import logging

from renku_data_services.authz.admin_sync import sync_admins_from_keycloak
from renku_data_services.authz.authz import Authz
from renku_data_services.background_jobs.config import QueueConfig, SyncConfig

logging.basicConfig(level=logging.INFO)


async def user_sync(args):
    """Sync users from keycloak."""
    config = SyncConfig.from_env()
    if config.total_user_sync:
        await config.syncer.users_sync(config.kc_api)
        await sync_admins_from_keycloak(config.kc_api, Authz(config.authz_config))
    else:
        await config.syncer.events_sync(config.kc_api)
        await sync_admins_from_keycloak(config.kc_api, Authz(config.authz_config))


async def send_messages(args):
    """Send pending message queue messages."""
    config = QueueConfig.from_env()
    while True:
        await config.event_repo.send_pending_events()
        await asyncio.sleep(1.0)


async def main():
    """Run data services background jobs."""
    parser = argparse.ArgumentParser(prog="Data Service Background Jobs")
    subparsers = parser.add_subparsers(help="Background job to run")

    user_sync_parser = subparsers.add_parser("user_sync", help="sync users from keycloak into data services")
    user_sync_parser.set_defaults(func=user_sync)

    send_messages_parser = subparsers.add_parser("send_messages", help="send outstanding message queue messages")
    send_messages_parser.set_defaults(func=send_messages)

    args = parser.parse_args()
    await args.func(args)


if __name__ == "__main__":
    asyncio.run(main())
