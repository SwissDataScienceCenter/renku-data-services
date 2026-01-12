"""Dependency management for data tasks."""

from dataclasses import dataclass

from renku_data_services.authz.authz import Authz
from renku_data_services.data_tasks.config import Config
from renku_data_services.metrics.core import StagingMetricsService
from renku_data_services.metrics.db import MetricsRepository
from renku_data_services.namespace.db import GroupRepository
from renku_data_services.project.db import ProjectRepository
from renku_data_services.search.db import SearchUpdatesRepo
from renku_data_services.session.db import SessionRepository
from renku_data_services.session.tasks import SessionTasks
from renku_data_services.users.db import UserRepo, UsersSync
from renku_data_services.users.dummy_kc_api import DummyKeycloakAPI
from renku_data_services.users.kc_api import IKeycloakAPI, KeycloakAPI
from renku_data_services.users.models import UnsavedUserInfo


@dataclass
class DependencyManager:
    """Configuration for the Data service."""

    config: Config
    search_updates_repo: SearchUpdatesRepo
    metrics_repo: MetricsRepository
    group_repo: GroupRepository
    project_repo: ProjectRepository
    authz: Authz
    syncer: UsersSync
    kc_api: IKeycloakAPI
    session_tasks: SessionTasks

    @classmethod
    def from_env(cls, cfg: Config | None = None) -> "DependencyManager":
        """Create a config from environment variables."""
        if cfg is None:
            cfg = Config.from_env()
        search_updates_repo = SearchUpdatesRepo(cfg.db.async_session_maker)
        metrics_repo = MetricsRepository(cfg.db.async_session_maker)
        metrics = StagingMetricsService(enabled=cfg.posthog.enabled, metrics_repo=metrics_repo)
        authz = Authz(cfg.authz)
        group_repo = GroupRepository(
            cfg.db.async_session_maker,
            group_authz=authz,
            search_updates_repo=search_updates_repo,
        )
        project_repo = ProjectRepository(
            session_maker=cfg.db.async_session_maker,
            group_repo=group_repo,
            search_updates_repo=search_updates_repo,
            authz=authz,
        )
        user_repo = UserRepo(
            session_maker=cfg.db.async_session_maker,
            group_repo=group_repo,
            search_updates_repo=search_updates_repo,
            encryption_key=None,
            metrics=metrics,
            authz=authz,
        )
        session_environment_repo = SessionRepository.make_session_environment_repo(
            session_maker=cfg.db.async_session_maker,
            project_authz=authz,
        )
        syncer = UsersSync(
            cfg.db.async_session_maker,
            group_repo=group_repo,
            user_repo=user_repo,
            metrics=metrics,
            authz=authz,
        )
        session_tasks = SessionTasks(session_environment_repo=session_environment_repo)
        kc_api: IKeycloakAPI
        if cfg.dummy_stores:
            dummy_users = [
                UnsavedUserInfo(id="user1", first_name="user1", last_name="doe", email="user1@doe.com"),
                UnsavedUserInfo(id="user2", first_name="user2", last_name="doe", email="user2@doe.com"),
            ]
            kc_api = DummyKeycloakAPI(users=[i.to_keycloak_dict() for i in dummy_users])
        else:
            assert cfg.keycloak is not None
            kc_api = KeycloakAPI(
                keycloak_url=cfg.keycloak.url,
                client_id=cfg.keycloak.client_id,
                client_secret=cfg.keycloak.client_secret,
                realm=cfg.keycloak.realm,
            )

        return cls(
            config=cfg,
            search_updates_repo=search_updates_repo,
            metrics_repo=metrics_repo,
            group_repo=group_repo,
            project_repo=project_repo,
            authz=authz,
            syncer=syncer,
            kc_api=kc_api,
            session_tasks=session_tasks,
        )
