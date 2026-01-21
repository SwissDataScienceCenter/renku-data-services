"""Dependency management for data tasks."""

from dataclasses import dataclass

from renku_data_services.authz.authz import Authz
from renku_data_services.crc.db import ClusterRepository
from renku_data_services.data_tasks.config import Config
from renku_data_services.k8s.clients import K8sClusterClientsPool
from renku_data_services.k8s.config import KubeConfigEnv, get_clusters
from renku_data_services.k8s.db import K8sDbCache
from renku_data_services.metrics.core import StagingMetricsService
from renku_data_services.metrics.db import MetricsRepository
from renku_data_services.namespace.db import GroupRepository
from renku_data_services.notebooks.constants import AMALTHEA_SESSION_GVK, JUPYTER_SESSION_GVK
from renku_data_services.project.db import ProjectRepository
from renku_data_services.resource_usage.core import ResourceRequestsFetch, ResourcesRequestRecorder
from renku_data_services.resource_usage.db import ResourceRequestsRepo
from renku_data_services.search.db import SearchUpdatesRepo
from renku_data_services.session.constants import BUILD_RUN_GVK, TASK_RUN_GVK
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
    resource_requests_recorder: ResourcesRequestRecorder

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

        cluster_repo = ClusterRepository(cfg.db.async_session_maker)
        k8s_db_cache = K8sDbCache(cfg.db.async_session_maker)
        default_kubeconfig = KubeConfigEnv()
        k8s_client = K8sClusterClientsPool(
            lambda: get_clusters(
                kube_conf_root_dir=cfg.k8s_config_root,
                default_kubeconfig=default_kubeconfig,
                cluster_repo=cluster_repo,
                cache=k8s_db_cache,
                kinds_to_cache=[AMALTHEA_SESSION_GVK, JUPYTER_SESSION_GVK, BUILD_RUN_GVK, TASK_RUN_GVK],
            ),
        )

        resource_requests_recorder = ResourcesRequestRecorder(
            repo=ResourceRequestsRepo(cfg.db.async_session_maker), fetch=ResourceRequestsFetch(k8s_client)
        )
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
            resource_requests_recorder=resource_requests_recorder,
        )
