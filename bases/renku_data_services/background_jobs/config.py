"""Configurations for background jobs."""

import os
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from renku_data_services.authz.authz import Authz
from renku_data_services.authz.config import AuthzConfig
from renku_data_services.data_connectors.migration_utils import DataConnectorMigrationTool
from renku_data_services.errors import errors
from renku_data_services.message_queue.config import RedisConfig
from renku_data_services.message_queue.db import EventRepository
from renku_data_services.message_queue.redis_queue import RedisQueue
from renku_data_services.namespace.db import GroupRepository
from renku_data_services.project.db import ProjectRepository
from renku_data_services.users.db import UsersSync
from renku_data_services.users.kc_api import IKeycloakAPI, KeycloakAPI


@dataclass
class SyncConfig:
    """Main configuration."""

    syncer: UsersSync
    kc_api: IKeycloakAPI
    authz_config: AuthzConfig
    group_repo: GroupRepository
    event_repo: EventRepository
    project_repo: ProjectRepository

    # NEW
    data_connector_migration_tool: DataConnectorMigrationTool

    session_maker: Callable[..., AsyncSession]

    @classmethod
    def from_env(cls, prefix: str = "") -> "SyncConfig":
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
        engine = create_async_engine(async_sqlalchemy_url, pool_size=4, max_overflow=0, pool_timeout=600)
        session_maker: Callable[..., AsyncSession] = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)  # type: ignore[call-overload]
        redis = RedisConfig.from_env(prefix)
        message_queue = RedisQueue(redis)

        authz_config = AuthzConfig.from_env()
        event_repo = EventRepository(session_maker=session_maker, message_queue=message_queue)
        group_repo = GroupRepository(
            session_maker,
            event_repo=event_repo,
            group_authz=Authz(authz_config),
            message_queue=message_queue,
        )
        project_repo = ProjectRepository(
            session_maker=session_maker,
            message_queue=message_queue,
            event_repo=event_repo,
            group_repo=group_repo,
            authz=Authz(authz_config),
        )

        # NEW
        data_connector_migration_tool = DataConnectorMigrationTool(
            session_maker=session_maker,
            authz=Authz(authz_config),
        )

        syncer = UsersSync(
            session_maker,
            message_queue=message_queue,
            event_repo=event_repo,
            group_repo=group_repo,
            authz=Authz(authz_config),
        )
        keycloak_url = os.environ[f"{prefix}KEYCLOAK_URL"]
        client_id = os.environ[f"{prefix}KEYCLOAK_CLIENT_ID"]
        client_secret = os.environ[f"{prefix}KEYCLOAK_CLIENT_SECRET"]
        realm = os.environ.get(f"{prefix}KEYCLOAK_REALM", "Renku")
        kc_api = KeycloakAPI(keycloak_url=keycloak_url, client_id=client_id, client_secret=client_secret, realm=realm)
        return cls(
            syncer,
            kc_api,
            authz_config,
            group_repo,
            event_repo,
            project_repo,
            data_connector_migration_tool,
            session_maker,
        )
