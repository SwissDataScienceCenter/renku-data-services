"""Configurations for Keycloak syncing."""
import os
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from renku_data_services.errors import errors
from renku_data_services.message_queue.config import RedisConfig
from renku_data_services.message_queue.db import EventRepository
from renku_data_services.message_queue.redis_queue import RedisQueue
from renku_data_services.users.db import GroupRepository, UsersSync
from renku_data_services.users.kc_api import IKeycloakAPI, KeycloakAPI


@dataclass
class SyncConfig:
    """Main configuration."""

    syncer: UsersSync
    kc_api: IKeycloakAPI
    total_user_sync: bool = False

    @classmethod
    def from_env(cls, prefix: str = ""):
        """Generate a configuration from environment variables."""
        pg_host = os.environ.get(f"{prefix}DB_HOST", "localhost")
        pg_user = os.environ.get(f"{prefix}DB_USER", "renku")
        pg_port = os.environ.get(f"{prefix}DB_PORT", "5432")
        db_name = os.environ.get(f"{prefix}DB_NAME", "renku")
        pg_password = os.environ.get(f"{prefix}DB_PASSWORD")
        if pg_password is None:
            raise errors.ConfigurationError(
                message="Please provide a database password in the 'DB_PASSWORD' environment variable."
            )
        async_sqlalchemy_url = f"postgresql+asyncpg://{pg_user}:{pg_password}@{pg_host}:{pg_port}/{db_name}"
        # NOTE: the pool here is not used to serve HTTP requests, it is only used in background jobs.
        # Therefore, we want to consume very few connections and we can wait for an available connection
        # much longer than the default 30 seconds. In our tests syncing 15 users times out with the default.
        engine = create_async_engine(async_sqlalchemy_url, pool_size=2, max_overflow=0, pool_timeout=600)
        session_maker: Callable[..., AsyncSession] = sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )  # type: ignore[call-overload]
        redis = RedisConfig.from_env(prefix)
        message_queue = RedisQueue(redis)

        event_repo = EventRepository(session_maker=session_maker, message_queue=message_queue)
        group_repo = GroupRepository(session_maker)
        syncer = UsersSync(session_maker, message_queue=message_queue, event_repo=event_repo, group_repo=group_repo)
        keycloak_url = os.environ[f"{prefix}KEYCLOAK_URL"]
        client_id = os.environ[f"{prefix}KEYCLOAK_CLIENT_ID"]
        client_secret = os.environ[f"{prefix}KEYCLOAK_CLIENT_SECRET"]
        realm = os.environ.get(f"{prefix}KEYCLOAK_REALM", "Renku")
        kc_api = KeycloakAPI(keycloak_url=keycloak_url, client_id=client_id, client_secret=client_secret, realm=realm)
        total_user_sync = os.environ.get(f"{prefix}TOTAL_USER_SYNC", "false").lower() == "true"
        return cls(syncer, kc_api, total_user_sync)
