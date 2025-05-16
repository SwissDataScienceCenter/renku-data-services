"""Dependency management for background jobs."""

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from renku_data_services.authz.authz import Authz
from renku_data_services.background_jobs.config import SyncConfig
from renku_data_services.data_connectors.db import DataConnectorRepository
from renku_data_services.data_connectors.migration_utils import DataConnectorMigrationTool
from renku_data_services.message_queue.db import EventRepository
from renku_data_services.message_queue.redis_queue import RedisQueue
from renku_data_services.namespace.db import GroupRepository
from renku_data_services.project.db import ProjectRepository
from renku_data_services.search.db import SearchUpdatesRepo
from renku_data_services.users.db import UserRepo, UsersSync
from renku_data_services.users.kc_api import IKeycloakAPI, KeycloakAPI


@dataclass
class DependencyManager:
    """Dependency management for background jobs."""

    config: SyncConfig

    syncer: UsersSync
    kc_api: IKeycloakAPI
    group_repo: GroupRepository
    event_repo: EventRepository
    project_repo: ProjectRepository
    authz: Authz
    data_connector_migration_tool: DataConnectorMigrationTool
    session_maker: Callable[..., AsyncSession]

    @classmethod
    def from_env(cls, config: SyncConfig | None = None) -> "DependencyManager":
        """Generate a configuration from environment variables."""
        if config is None:
            config = SyncConfig.from_env()
        # NOTE: the pool here is not used to serve HTTP requests, it is only used in background jobs.
        # Therefore, we want to consume very few connections and we can wait for an available connection
        # much longer than the default 30 seconds. In our tests syncing 15 users times out with the default.
        engine = create_async_engine(config.db.conn_url(), pool_size=4, max_overflow=0, pool_timeout=600)
        session_maker: Callable[..., AsyncSession] = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)  # type: ignore[call-overload]
        message_queue = RedisQueue(config.redis)

        event_repo = EventRepository(session_maker=session_maker, message_queue=message_queue)
        search_updates_repo = SearchUpdatesRepo(session_maker=session_maker)
        authz = Authz(config.authz)
        group_repo = GroupRepository(
            session_maker,
            event_repo=event_repo,
            group_authz=authz,
            message_queue=message_queue,
            search_updates_repo=search_updates_repo,
        )
        project_repo = ProjectRepository(
            session_maker=session_maker,
            message_queue=message_queue,
            event_repo=event_repo,
            group_repo=group_repo,
            search_updates_repo=search_updates_repo,
            authz=authz,
        )
        data_connector_repo = DataConnectorRepository(
            session_maker=session_maker,
            authz=authz,
            project_repo=project_repo,
            group_repo=group_repo,
            search_updates_repo=search_updates_repo,
        )
        data_connector_migration_tool = DataConnectorMigrationTool(
            session_maker=session_maker,
            data_connector_repo=data_connector_repo,
            project_repo=project_repo,
            authz=authz,
        )
        user_repo = UserRepo(
            session_maker=session_maker,
            message_queue=message_queue,
            event_repo=event_repo,
            group_repo=group_repo,
            search_updates_repo=search_updates_repo,
            encryption_key=None,
            authz=authz,
        )
        syncer = UsersSync(
            session_maker,
            message_queue=message_queue,
            event_repo=event_repo,
            group_repo=group_repo,
            user_repo=user_repo,
            authz=authz,
        )

        kc_api = KeycloakAPI(
            keycloak_url=config.keycloak.url,
            client_id=config.keycloak.client_id,
            client_secret=config.keycloak.client_secret,
            realm=config.keycloak.realm,
        )
        return cls(
            config=config,
            syncer=syncer,
            kc_api=kc_api,
            group_repo=group_repo,
            event_repo=event_repo,
            project_repo=project_repo,
            authz=authz,
            data_connector_migration_tool=data_connector_migration_tool,
            session_maker=session_maker,
        )
