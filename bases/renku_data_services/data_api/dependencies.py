"""Dependency management for data api."""

import functools
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from authlib.integrations.httpx_client import AsyncOAuth2Client
from jwt import PyJWKClient
from yaml import safe_load

import renku_data_services.base_models as base_models
import renku_data_services.connected_services
import renku_data_services.crc
import renku_data_services.data_connectors
import renku_data_services.platform
import renku_data_services.repositories
import renku_data_services.search
import renku_data_services.storage
import renku_data_services.users
from renku_data_services import errors
from renku_data_services.authn.dummy import DummyAuthenticator, DummyUserStore
from renku_data_services.authn.gitlab import GitlabAuthenticator
from renku_data_services.authn.keycloak import KcUserStore, KeycloakAuthenticator
from renku_data_services.authz.authz import Authz
from renku_data_services.authz.config import AuthzConfig
from renku_data_services.connected_services.db import ConnectedServicesRepository
from renku_data_services.crc import models as crc_models
from renku_data_services.crc.db import ClusterRepository, ResourcePoolRepository, UserRepository
from renku_data_services.crc.server_options import (
    ServerOptions,
    ServerOptionsDefaults,
    generate_default_resource_pool,
)
from renku_data_services.data_api.config import Config
from renku_data_services.data_connectors.db import (
    DataConnectorRepository,
    DataConnectorSecretRepository,
)
from renku_data_services.git.gitlab import DummyGitlabAPI, GitlabAPI
from renku_data_services.k8s.clients import (
    DummyCoreClient,
    DummySchedulingClient,
    K8sClusterClientsPool,
    K8sCoreClient,
    K8sSchedulingClient,
)
from renku_data_services.k8s.config import KubeConfigEnv
from renku_data_services.k8s.quota import QuotaRepository
from renku_data_services.k8s_watcher import K8sDbCache
from renku_data_services.message_queue.db import EventRepository, ReprovisioningRepository
from renku_data_services.message_queue.interface import IMessageQueue
from renku_data_services.message_queue.redis_queue import RedisQueue
from renku_data_services.metrics.core import StagingMetricsService
from renku_data_services.metrics.db import MetricsRepository
from renku_data_services.namespace.db import GroupRepository
from renku_data_services.notebooks.config import NotebooksConfig, get_clusters
from renku_data_services.notebooks.constants import AMALTHEA_SESSION_GVK, JUPYTER_SESSION_GVK
from renku_data_services.platform.db import PlatformRepository
from renku_data_services.project.db import (
    ProjectMemberRepository,
    ProjectMigrationRepository,
    ProjectRepository,
    ProjectSessionSecretRepository,
)
from renku_data_services.repositories.db import GitRepositoriesRepository
from renku_data_services.search.db import SearchUpdatesRepo
from renku_data_services.search.reprovision import SearchReprovision
from renku_data_services.secrets.db import LowLevelUserSecretsRepo, UserSecretsRepo
from renku_data_services.session.constants import BUILD_RUN_GVK, TASK_RUN_GVK
from renku_data_services.session.db import SessionRepository
from renku_data_services.session.k8s_client import ShipwrightClient
from renku_data_services.storage.db import StorageRepository
from renku_data_services.users.db import UserPreferencesRepository
from renku_data_services.users.db import UserRepo as KcUserRepo
from renku_data_services.users.dummy_kc_api import DummyKeycloakAPI
from renku_data_services.users.kc_api import IKeycloakAPI, KeycloakAPI
from renku_data_services.users.models import UnsavedUserInfo
from renku_data_services.utils.core import merge_api_specs, oidc_discovery

default_resource_pool = crc_models.ResourcePool(
    name="default",
    classes=[
        crc_models.ResourceClass(
            name="small",
            cpu=0.5,
            memory=1,
            max_storage=20,
            gpu=0,
            default=True,
        ),
        crc_models.ResourceClass(
            name="large",
            cpu=1.0,
            memory=2,
            max_storage=20,
            gpu=0,
            default=False,
        ),
    ],
    quota=None,
    public=True,
    default=True,
)


@dataclass
class DependencyManager:
    """Configuration for the Data service."""

    config: Config

    user_store: base_models.UserStore
    authenticator: base_models.Authenticator
    gitlab_authenticator: base_models.Authenticator
    quota_repo: QuotaRepository
    gitlab_client: base_models.GitlabAPIProtocol
    kc_api: IKeycloakAPI
    message_queue: IMessageQueue
    gitlab_url: str | None
    nb_config: NotebooksConfig

    authz_config: AuthzConfig = field(default_factory=lambda: AuthzConfig.from_env())
    spec: dict[str, Any] = field(init=False, repr=False, default_factory=dict)
    app_name: str = "renku_data_services"
    default_resource_pool_file: str | None = None
    default_resource_pool: crc_models.ResourcePool = default_resource_pool
    async_oauth2_client_class: type[AsyncOAuth2Client] = AsyncOAuth2Client
    _user_repo: UserRepository | None = field(default=None, repr=False, init=False)
    _rp_repo: ResourcePoolRepository | None = field(default=None, repr=False, init=False)
    _storage_repo: StorageRepository | None = field(default=None, repr=False, init=False)
    _project_repo: ProjectRepository | None = field(default=None, repr=False, init=False)
    _project_migration_repo: ProjectMigrationRepository | None = field(default=None, repr=False, init=False)
    _group_repo: GroupRepository | None = field(default=None, repr=False, init=False)
    _event_repo: EventRepository | None = field(default=None, repr=False, init=False)
    _reprovisioning_repo: ReprovisioningRepository | None = field(default=None, repr=False, init=False)
    _search_updates_repo: SearchUpdatesRepo | None = field(default=None, repr=False, init=False)
    _search_reprovisioning: SearchReprovision | None = field(default=None, repr=False, init=False)
    _session_repo: SessionRepository | None = field(default=None, repr=False, init=False)
    _user_preferences_repo: UserPreferencesRepository | None = field(default=None, repr=False, init=False)
    _kc_user_repo: KcUserRepo | None = field(default=None, repr=False, init=False)
    _low_level_user_secrets_repo: LowLevelUserSecretsRepo | None = field(default=None, repr=False, init=False)
    _user_secrets_repo: UserSecretsRepo | None = field(default=None, repr=False, init=False)
    _project_member_repo: ProjectMemberRepository | None = field(default=None, repr=False, init=False)
    _project_session_secret_repo: ProjectSessionSecretRepository | None = field(default=None, repr=False, init=False)
    _connected_services_repo: ConnectedServicesRepository | None = field(default=None, repr=False, init=False)
    _git_repositories_repo: GitRepositoriesRepository | None = field(default=None, repr=False, init=False)
    _platform_repo: PlatformRepository | None = field(default=None, repr=False, init=False)
    _data_connector_repo: DataConnectorRepository | None = field(default=None, repr=False, init=False)
    _data_connector_secret_repo: DataConnectorSecretRepository | None = field(default=None, repr=False, init=False)
    _cluster_repo: ClusterRepository | None = field(default=None, repr=False, init=False)
    _metrics_repo: MetricsRepository | None = field(default=None, repr=False, init=False)
    _metrics: StagingMetricsService | None = field(default=None, repr=False, init=False)
    _shipwright_client: ShipwrightClient | None = field(default=None, repr=False, init=False)

    @staticmethod
    @functools.cache
    def load_apispec() -> dict[str, Any]:
        """Load apispec with caching.

        Note: loading these files takes quite some time and is repeated for each test. Having
        them cached in this method reduces that time significantly.
        """
        files = [
            renku_data_services.crc.__file__,
            renku_data_services.storage.__file__,
            renku_data_services.users.__file__,
            renku_data_services.project.__file__,
            renku_data_services.namespace.__file__,
            renku_data_services.session.__file__,
            renku_data_services.connected_services.__file__,
            renku_data_services.repositories.__file__,
            renku_data_services.notebooks.__file__,
            renku_data_services.platform.__file__,
            renku_data_services.message_queue.__file__,
            renku_data_services.data_connectors.__file__,
            renku_data_services.search.__file__,
        ]

        api_specs = []

        # NOTE: Read spec files required for Swagger
        for file in files:
            spec_file = Path(file).resolve().parent / "api.spec.yaml"
            with open(spec_file) as f:
                api_specs.append(safe_load(f))

        return merge_api_specs(*api_specs)

    def __post_init__(self) -> None:
        self.spec = self.load_apispec()

        if self.default_resource_pool_file is not None:
            with open(self.default_resource_pool_file) as f:
                self.default_resource_pool = crc_models.ResourcePool.from_dict(safe_load(f))
        if (
            self.config.server_options.defaults_path is not None
            and self.config.server_options.ui_choices_path is not None
        ):
            with open(self.config.server_options.ui_choices_path) as f:
                options = ServerOptions.model_validate(safe_load(f))
            with open(self.config.server_options.defaults_path) as f:
                defaults = ServerOptionsDefaults.model_validate(safe_load(f))
            self.default_resource_pool = generate_default_resource_pool(options, defaults)

        self.authz = Authz(self.authz_config)

    @property
    def user_repo(self) -> UserRepository:
        """The DB adapter for users of resource pools and classes."""
        if not self._user_repo:
            self._user_repo = UserRepository(
                session_maker=self.config.db.async_session_maker,
                quotas_repo=self.quota_repo,
                user_repo=self.kc_user_repo,
            )
        return self._user_repo

    @property
    def rp_repo(self) -> ResourcePoolRepository:
        """The DB adapter for resource pools."""
        if not self._rp_repo:
            self._rp_repo = ResourcePoolRepository(
                session_maker=self.config.db.async_session_maker, quotas_repo=self.quota_repo
            )
        return self._rp_repo

    @property
    def storage_repo(self) -> StorageRepository:
        """The DB adapter for V1 cloud storage configs."""
        if not self._storage_repo:
            self._storage_repo = StorageRepository(
                session_maker=self.config.db.async_session_maker,
                gitlab_client=self.gitlab_client,
                user_repo=self.kc_user_repo,
                secret_service_public_key=self.config.secrets.public_key,
            )
        return self._storage_repo

    @property
    def event_repo(self) -> EventRepository:
        """The DB adapter for cloud event configs."""
        if not self._event_repo:
            self._event_repo = EventRepository(
                session_maker=self.config.db.async_session_maker, message_queue=self.message_queue
            )
        return self._event_repo

    @property
    def reprovisioning_repo(self) -> ReprovisioningRepository:
        """The DB adapter for reprovisioning."""
        if not self._reprovisioning_repo:
            self._reprovisioning_repo = ReprovisioningRepository(session_maker=self.config.db.async_session_maker)
        return self._reprovisioning_repo

    @property
    def search_updates_repo(self) -> SearchUpdatesRepo:
        """The DB adapter to the search_updates table."""
        if not self._search_updates_repo:
            self._search_updates_repo = SearchUpdatesRepo(session_maker=self.config.db.async_session_maker)
        return self._search_updates_repo

    @property
    def search_reprovisioning(self) -> SearchReprovision:
        """The SearchReprovisioning class."""
        if not self._search_reprovisioning:
            self._search_reprovisioning = SearchReprovision(
                search_updates_repo=self.search_updates_repo,
                reprovisioning_repo=self.reprovisioning_repo,
                solr_config=self.config.solr,
                user_repo=self.kc_user_repo,
                group_repo=self.group_repo,
                project_repo=self.project_repo,
                data_connector_repo=self.data_connector_repo,
            )
        return self._search_reprovisioning

    @property
    def project_repo(self) -> ProjectRepository:
        """The DB adapter for Renku native projects."""
        if not self._project_repo:
            self._project_repo = ProjectRepository(
                session_maker=self.config.db.async_session_maker,
                authz=self.authz,
                message_queue=self.message_queue,
                event_repo=self.event_repo,
                group_repo=self.group_repo,
                search_updates_repo=self.search_updates_repo,
            )
        return self._project_repo

    @property
    def project_migration_repo(self) -> ProjectMigrationRepository:
        """The DB adapter for Renku native project migrations."""
        if not self._project_migration_repo:
            self._project_migration_repo = ProjectMigrationRepository(
                session_maker=self.config.db.async_session_maker,
                authz=self.authz,
                message_queue=self.message_queue,
                project_repo=self.project_repo,
                event_repo=self.event_repo,
                session_repo=self.session_repo,
            )
        return self._project_migration_repo

    @property
    def project_member_repo(self) -> ProjectMemberRepository:
        """The DB adapter for Renku native projects members."""
        if not self._project_member_repo:
            self._project_member_repo = ProjectMemberRepository(
                session_maker=self.config.db.async_session_maker,
                authz=self.authz,
                event_repo=self.event_repo,
                message_queue=self.message_queue,
            )
        return self._project_member_repo

    @property
    def project_session_secret_repo(self) -> ProjectSessionSecretRepository:
        """The DB adapter for session secrets on projects."""
        if not self._project_session_secret_repo:
            self._project_session_secret_repo = ProjectSessionSecretRepository(
                session_maker=self.config.db.async_session_maker,
                authz=self.authz,
                user_repo=self.kc_user_repo,
                secret_service_public_key=self.config.secrets.public_key,
            )
        return self._project_session_secret_repo

    @property
    def group_repo(self) -> GroupRepository:
        """The DB adapter for Renku groups."""
        if not self._group_repo:
            self._group_repo = GroupRepository(
                session_maker=self.config.db.async_session_maker,
                event_repo=self.event_repo,
                group_authz=self.authz,
                message_queue=self.message_queue,
                search_updates_repo=self.search_updates_repo,
            )
        return self._group_repo

    @property
    def session_repo(self) -> SessionRepository:
        """The DB adapter for sessions."""
        if not self._session_repo:
            self._session_repo = SessionRepository(
                session_maker=self.config.db.async_session_maker,
                project_authz=self.authz,
                resource_pools=self.rp_repo,
                shipwright_client=self.shipwright_client,
                builds_config=self.config.builds,
            )
        return self._session_repo

    @property
    def user_preferences_repo(self) -> UserPreferencesRepository:
        """The DB adapter for user preferences."""
        if not self._user_preferences_repo:
            self._user_preferences_repo = UserPreferencesRepository(
                session_maker=self.config.db.async_session_maker,
                user_preferences_config=self.config.user_preferences,
            )
        return self._user_preferences_repo

    @property
    def kc_user_repo(self) -> KcUserRepo:
        """The DB adapter for users."""
        if not self._kc_user_repo:
            self._kc_user_repo = KcUserRepo(
                session_maker=self.config.db.async_session_maker,
                message_queue=self.message_queue,
                event_repo=self.event_repo,
                group_repo=self.group_repo,
                search_updates_repo=self.search_updates_repo,
                encryption_key=self.config.secrets.encryption_key,
                authz=self.authz,
            )
        return self._kc_user_repo

    @property
    def user_secrets_repo(self) -> UserSecretsRepo:
        """The DB adapter for user secrets storage."""
        if not self._user_secrets_repo:
            low_level_user_secrets_repo = LowLevelUserSecretsRepo(
                session_maker=self.config.db.async_session_maker,
            )
            self._user_secrets_repo = UserSecretsRepo(
                session_maker=self.config.db.async_session_maker,
                low_level_repo=low_level_user_secrets_repo,
                user_repo=self.kc_user_repo,
                secret_service_public_key=self.config.secrets.public_key,
            )
        return self._user_secrets_repo

    @property
    def connected_services_repo(self) -> ConnectedServicesRepository:
        """The DB adapter for connected services."""
        if not self._connected_services_repo:
            self._connected_services_repo = ConnectedServicesRepository(
                session_maker=self.config.db.async_session_maker,
                encryption_key=self.config.secrets.encryption_key,
                async_oauth2_client_class=self.async_oauth2_client_class,
                internal_gitlab_url=self.gitlab_url,
            )
        return self._connected_services_repo

    @property
    def git_repositories_repo(self) -> GitRepositoriesRepository:
        """The DB adapter for repositories."""
        if not self._git_repositories_repo:
            self._git_repositories_repo = GitRepositoriesRepository(
                session_maker=self.config.db.async_session_maker,
                connected_services_repo=self.connected_services_repo,
                internal_gitlab_url=self.gitlab_url,
            )
        return self._git_repositories_repo

    @property
    def platform_repo(self) -> PlatformRepository:
        """The DB adapter for the platform configuration."""
        if not self._platform_repo:
            self._platform_repo = PlatformRepository(
                session_maker=self.config.db.async_session_maker,
            )
        return self._platform_repo

    @property
    def data_connector_repo(self) -> DataConnectorRepository:
        """The DB adapter for data connectors."""
        if not self._data_connector_repo:
            self._data_connector_repo = DataConnectorRepository(
                session_maker=self.config.db.async_session_maker,
                authz=self.authz,
                project_repo=self.project_repo,
                group_repo=self.group_repo,
                search_updates_repo=self.search_updates_repo,
            )
        return self._data_connector_repo

    @property
    def data_connector_secret_repo(self) -> DataConnectorSecretRepository:
        """The DB adapter for data connector secrets."""
        if not self._data_connector_secret_repo:
            self._data_connector_secret_repo = DataConnectorSecretRepository(
                session_maker=self.config.db.async_session_maker,
                data_connector_repo=self.data_connector_repo,
                user_repo=self.kc_user_repo,
                secret_service_public_key=self.config.secrets.public_key,
                authz=self.authz,
            )
        return self._data_connector_secret_repo

    @property
    def cluster_repo(self) -> ClusterRepository:
        """The DB adapter for cluster descriptions."""
        if not self._cluster_repo:
            self._cluster_repo = ClusterRepository(session_maker=self.config.db.async_session_maker)

        return self._cluster_repo

    @property
    def metrics_repo(self) -> MetricsRepository:
        """The DB adapter for metrics."""
        if not self._metrics_repo:
            self._metrics_repo = MetricsRepository(session_maker=self.config.db.async_session_maker)
        return self._metrics_repo

    @property
    def metrics(self) -> StagingMetricsService:
        """The metrics service interface."""
        if not self._metrics:
            self._metrics = StagingMetricsService(enabled=self.config.posthog.enabled, metrics_repo=self.metrics_repo)
        return self._metrics

    @property
    def shipwright_client(self) -> ShipwrightClient | None:
        """The shipwright build client."""
        if not self.config.builds.enabled or self.config.dummy_stores:
            return None
        if self._shipwright_client is None:
            # NOTE: we need to get an async client as a sync client can't be used in an async way
            # But all the config code is not async, so we need to drop into the running loop, if there is one
            kr8s_api = KubeConfigEnv().api()
            k8s_db_cache = K8sDbCache(self.config.db.async_session_maker)
            client = K8sClusterClientsPool(
                clusters=get_clusters("/secrets/kube_configs", namespace=self.config.k8s_namespace, api=kr8s_api),
                cache=k8s_db_cache,
                kinds_to_cache=[AMALTHEA_SESSION_GVK, JUPYTER_SESSION_GVK, BUILD_RUN_GVK, TASK_RUN_GVK],
            )
            self._shipwright_client = ShipwrightClient(
                client=client,
                namespace=self.config.k8s_namespace,
            )

        return self._shipwright_client

    @classmethod
    def from_env(cls, prefix: str = "") -> "DependencyManager":
        """Create a config from environment variables."""

        user_store: base_models.UserStore
        authenticator: base_models.Authenticator
        gitlab_authenticator: base_models.Authenticator
        gitlab_client: base_models.GitlabAPIProtocol

        config = Config.from_env()
        kc_api: IKeycloakAPI
        gitlab_url: str | None

        if config.dummy_stores:
            authenticator = DummyAuthenticator()
            gitlab_authenticator = DummyAuthenticator()
            quota_repo = QuotaRepository(
                DummyCoreClient({}, {}), DummySchedulingClient({}), namespace=config.k8s_namespace
            )
            user_always_exists = os.environ.get("DUMMY_USERSTORE_USER_ALWAYS_EXISTS", "true").lower() == "true"
            user_store = DummyUserStore(user_always_exists=user_always_exists)
            gitlab_client = DummyGitlabAPI()
            dummy_users = [
                UnsavedUserInfo(id="user1", first_name="user1", last_name="doe", email="user1@doe.com"),
                UnsavedUserInfo(id="user2", first_name="user2", last_name="doe", email="user2@doe.com"),
            ]
            kc_api = DummyKeycloakAPI(users=[i.to_keycloak_dict() for i in dummy_users])
            gitlab_url = None
        else:
            quota_repo = QuotaRepository(K8sCoreClient(), K8sSchedulingClient(), namespace=config.k8s_namespace)
            assert config.keycloak is not None
            oidc_disc_data = oidc_discovery(config.keycloak.keycloak_url, config.keycloak.keycloak_realm)
            jwks_url = oidc_disc_data.get("jwks_uri")
            if jwks_url is None:
                raise errors.ConfigurationError(
                    message="The JWKS url for Keycloak cannot be found from the OIDC discovery endpoint."
                )
            jwks = PyJWKClient(jwks_url)
            authenticator = KeycloakAuthenticator(jwks=jwks, algorithms=config.keycloak.algorithms)
            assert config.gitlab_url is not None
            gitlab_authenticator = GitlabAuthenticator(gitlab_url=config.gitlab_url)
            user_store = KcUserStore(keycloak_url=config.keycloak.keycloak_url, realm=config.keycloak.keycloak_realm)
            gitlab_client = GitlabAPI(gitlab_url=config.gitlab_url)
            kc_api = KeycloakAPI(
                keycloak_url=config.keycloak.keycloak_url,
                client_id=config.keycloak.client_id,
                client_secret=config.keycloak.client_secret,
                realm=config.keycloak.keycloak_realm,
            )

        message_queue = RedisQueue(config.redis)
        nb_config = NotebooksConfig.from_env(config.db)

        return cls(
            config,
            authenticator=authenticator,
            gitlab_authenticator=gitlab_authenticator,
            gitlab_client=gitlab_client,
            user_store=user_store,
            quota_repo=quota_repo,
            kc_api=kc_api,
            message_queue=message_queue,
            gitlab_url=gitlab_url,
            nb_config=nb_config,
        )
