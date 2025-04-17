"""Configurations.

An important thing to note here is that the configuration classes in here
contain some getters (i.e. @property decorators) intentionally. This is done for
things that need a database connection and the purpose is that the database connection
is not initialized when the classes are initialized. Only if the properties that need
the database will instantiate a connection when they are used. And even in this case
a single connection will be reused. This allows for the configuration classes to be
instantiated multiple times without creating multiple database connections.
"""

import functools
import os
import secrets
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any, Optional

from authlib.integrations.httpx_client import AsyncOAuth2Client
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.types import PublicKeyTypes
from jwt import PyJWKClient
from pydantic import ValidationError as PydanticValidationError
from sanic.log import logger
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
from renku_data_services.app_config.server_options import (
    ServerOptions,
    ServerOptionsDefaults,
    generate_default_resource_pool,
)
from renku_data_services.authn.dummy import DummyAuthenticator, DummyUserStore
from renku_data_services.authn.gitlab import GitlabAuthenticator
from renku_data_services.authn.keycloak import KcUserStore, KeycloakAuthenticator
from renku_data_services.authz.authz import Authz
from renku_data_services.authz.config import AuthzConfig
from renku_data_services.connected_services.db import ConnectedServicesRepository
from renku_data_services.crc import models
from renku_data_services.crc.db import ResourcePoolRepository, UserRepository
from renku_data_services.data_connectors.db import (
    DataConnectorRepository,
    DataConnectorSecretRepository,
)
from renku_data_services.db_config import DBConfig
from renku_data_services.git.gitlab import DummyGitlabAPI, GitlabAPI
from renku_data_services.k8s.clients import DummyCoreClient, DummySchedulingClient, K8sCoreClient, K8sSchedulingClient
from renku_data_services.k8s.quota import QuotaRepository
from renku_data_services.message_queue.config import RedisConfig
from renku_data_services.message_queue.db import EventRepository, ReprovisioningRepository
from renku_data_services.message_queue.interface import IMessageQueue
from renku_data_services.message_queue.redis_queue import RedisQueue
from renku_data_services.namespace.db import GroupRepository
from renku_data_services.notebooks.config import NotebooksConfig
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
from renku_data_services.session import crs as session_crs
from renku_data_services.session.db import SessionRepository
from renku_data_services.session.k8s_client import ShipwrightClient
from renku_data_services.solr.solr_client import SolrClientConfig
from renku_data_services.storage.db import StorageRepository
from renku_data_services.users.config import UserPreferencesConfig
from renku_data_services.users.db import UserPreferencesRepository
from renku_data_services.users.db import UserRepo as KcUserRepo
from renku_data_services.users.dummy_kc_api import DummyKeycloakAPI
from renku_data_services.users.kc_api import IKeycloakAPI, KeycloakAPI
from renku_data_services.users.models import UnsavedUserInfo
from renku_data_services.utils.core import merge_api_specs, oidc_discovery

default_resource_pool = models.ResourcePool(
    name="default",
    classes=[
        models.ResourceClass(
            name="small",
            cpu=0.5,
            memory=1,
            max_storage=20,
            gpu=0,
            default=True,
        ),
        models.ResourceClass(
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
class SentryConfig:
    """Configuration for sentry."""

    enabled: bool
    dsn: str
    environment: str
    sample_rate: float = 0.2

    @classmethod
    def from_env(cls, prefix: str = "") -> "SentryConfig":
        """Create a config from environment variables."""
        enabled = os.environ.get(f"{prefix}SENTRY_ENABLED", "false").lower() == "true"
        dsn = os.environ.get(f"{prefix}SENTRY_DSN", "")
        environment = os.environ.get(f"{prefix}SENTRY_ENVIRONMENT", "")
        sample_rate = float(os.environ.get(f"{prefix}SENTRY_SAMPLE_RATE", "0.2"))

        return cls(enabled, dsn=dsn, environment=environment, sample_rate=sample_rate)


@dataclass
class TrustedProxiesConfig:
    """Configuration for trusted reverse proxies."""

    proxies_count: int | None = None
    real_ip_header: str | None = None

    @classmethod
    def from_env(cls, prefix: str = "") -> "TrustedProxiesConfig":
        """Create a config from environment variables."""
        proxies_count = int(os.environ.get(f"{prefix}PROXIES_COUNT") or "0")
        real_ip_header = os.environ.get(f"{prefix}REAL_IP_HEADER")
        return cls(proxies_count=proxies_count or None, real_ip_header=real_ip_header or None)


@dataclass
class BuildsConfig:
    """Configuration for container image builds."""

    shipwright_client: ShipwrightClient | None

    enabled: bool = False
    build_output_image_prefix: str | None = None
    vscodium_python_run_image: str | None = None
    build_strategy_name: str | None = None
    push_secret_name: str | None = None
    buildrun_retention_after_failed: timedelta | None = None
    buildrun_retention_after_succeeded: timedelta | None = None
    buildrun_build_timeout: timedelta | None = None
    node_selector: dict[str, str] | None = None
    tolerations: list[session_crs.Toleration] | None = None

    @classmethod
    def from_env(cls, prefix: str = "", namespace: str = "") -> "BuildsConfig":
        """Create a config from environment variables."""
        enabled = os.environ.get(f"{prefix}IMAGE_BUILDERS_ENABLED", "false").lower() == "true"
        build_output_image_prefix = os.environ.get(f"{prefix}BUILD_OUTPUT_IMAGE_PREFIX")
        vscodium_python_run_image = os.environ.get(f"{prefix}BUILD_VSCODIUM_PYTHON_RUN_IMAGE")
        build_strategy_name = os.environ.get(f"{prefix}BUILD_STRATEGY_NAME")
        push_secret_name = os.environ.get(f"{prefix}BUILD_PUSH_SECRET_NAME")
        buildrun_retention_after_failed_seconds = int(
            os.environ.get(f"{prefix}BUILD_RUN_RETENTION_AFTER_FAILED_SECONDS") or "0"
        )
        buildrun_retention_after_failed = (
            timedelta(seconds=buildrun_retention_after_failed_seconds)
            if buildrun_retention_after_failed_seconds > 0
            else None
        )
        buildrun_retention_after_succeeded_seconds = int(
            os.environ.get(f"{prefix}BUILD_RUN_RETENTION_AFTER_SUCCEEDED_SECONDS") or "0"
        )
        buildrun_retention_after_succeeded = (
            timedelta(seconds=buildrun_retention_after_succeeded_seconds)
            if buildrun_retention_after_succeeded_seconds > 0
            else None
        )
        buildrun_build_timeout_seconds = int(os.environ.get(f"{prefix}BUILD_RUN_BUILD_TIMEOUT") or "0")
        buildrun_build_timeout = (
            timedelta(seconds=buildrun_build_timeout_seconds) if buildrun_build_timeout_seconds > 0 else None
        )

        if os.environ.get(f"{prefix}DUMMY_STORES", "false").lower() == "true":
            shipwright_client = None
            enabled = True  # Enable image builds when running tests
        elif not enabled:
            shipwright_client = None
        else:
            # TODO: is there a reason to use a different cache URL here?
            cache_url = os.environ["NB_AMALTHEA_V2__CACHE_URL"]
            shipwright_client = ShipwrightClient(
                namespace=namespace,
                cache_url=cache_url,
            )

        node_selector: dict[str, str] | None = None
        node_selector_str = os.environ.get(f"{prefix}BUILD_NODE_SELECTOR")
        if node_selector_str:
            try:
                node_selector = session_crs.NodeSelector.model_validate_json(node_selector_str).root
            except PydanticValidationError:
                logger.error(
                    f"Could not validate {prefix}BUILD_NODE_SELECTOR. Will not use node selector for image builds."
                )

        tolerations: list[session_crs.Toleration] | None = None
        tolerations_str = os.environ.get(f"{prefix}BUILD_NODE_TOLERATIONS")
        if tolerations_str:
            try:
                tolerations = session_crs.Tolerations.model_validate_json(tolerations_str).root
            except PydanticValidationError:
                logger.error(
                    f"Could not validate {prefix}BUILD_NODE_TOLERATIONS. Will not use tolerations for image builds."
                )

        return cls(
            enabled=enabled or False,
            build_output_image_prefix=build_output_image_prefix or None,
            vscodium_python_run_image=vscodium_python_run_image or None,
            build_strategy_name=build_strategy_name or None,
            push_secret_name=push_secret_name or None,
            shipwright_client=shipwright_client,
            buildrun_retention_after_failed=buildrun_retention_after_failed,
            buildrun_retention_after_succeeded=buildrun_retention_after_succeeded,
            buildrun_build_timeout=buildrun_build_timeout,
            node_selector=node_selector,
            tolerations=tolerations,
        )


@dataclass
class Config:
    """Configuration for the Data service."""

    user_store: base_models.UserStore
    authenticator: base_models.Authenticator
    gitlab_authenticator: base_models.Authenticator
    quota_repo: QuotaRepository
    user_preferences_config: UserPreferencesConfig
    db: DBConfig
    redis: RedisConfig
    sentry: SentryConfig
    trusted_proxies: TrustedProxiesConfig
    gitlab_client: base_models.GitlabAPIProtocol
    kc_api: IKeycloakAPI
    message_queue: IMessageQueue
    gitlab_url: str | None
    nb_config: NotebooksConfig
    builds_config: BuildsConfig

    secrets_service_public_key: rsa.RSAPublicKey
    """The public key of the secrets service, used to encrypt user secrets that only it can decrypt."""
    encryption_key: bytes = field(repr=False)
    """The encryption key to encrypt user keys at rest in the database."""

    authz_config: AuthzConfig = field(default_factory=lambda: AuthzConfig.from_env())
    solr_config: SolrClientConfig = field(default_factory=lambda: SolrClientConfig.from_env())
    spec: dict[str, Any] = field(init=False, repr=False, default_factory=dict)
    version: str = "0.0.1"
    app_name: str = "renku_data_services"
    default_resource_pool_file: Optional[str] = None
    default_resource_pool: models.ResourcePool = default_resource_pool
    server_options_file: Optional[str] = None
    server_defaults_file: Optional[str] = None
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
                self.default_resource_pool = models.ResourcePool.from_dict(safe_load(f))
        if self.server_defaults_file is not None and self.server_options_file is not None:
            with open(self.server_options_file) as f:
                options = ServerOptions.model_validate(safe_load(f))
            with open(self.server_defaults_file) as f:
                defaults = ServerOptionsDefaults.model_validate(safe_load(f))
            self.default_resource_pool = generate_default_resource_pool(options, defaults)

        self.authz = Authz(self.authz_config)

    @property
    def user_repo(self) -> UserRepository:
        """The DB adapter for users of resoure pools and classes."""
        if not self._user_repo:
            self._user_repo = UserRepository(
                session_maker=self.db.async_session_maker, quotas_repo=self.quota_repo, user_repo=self.kc_user_repo
            )
        return self._user_repo

    @property
    def rp_repo(self) -> ResourcePoolRepository:
        """The DB adapter for resource pools."""
        if not self._rp_repo:
            self._rp_repo = ResourcePoolRepository(
                session_maker=self.db.async_session_maker, quotas_repo=self.quota_repo
            )
        return self._rp_repo

    @property
    def storage_repo(self) -> StorageRepository:
        """The DB adapter for V1 cloud storage configs."""
        if not self._storage_repo:
            self._storage_repo = StorageRepository(
                session_maker=self.db.async_session_maker,
                gitlab_client=self.gitlab_client,
                user_repo=self.kc_user_repo,
                secret_service_public_key=self.secrets_service_public_key,
            )
        return self._storage_repo

    @property
    def event_repo(self) -> EventRepository:
        """The DB adapter for cloud event configs."""
        if not self._event_repo:
            self._event_repo = EventRepository(
                session_maker=self.db.async_session_maker, message_queue=self.message_queue
            )
        return self._event_repo

    @property
    def reprovisioning_repo(self) -> ReprovisioningRepository:
        """The DB adapter for reprovisioning."""
        if not self._reprovisioning_repo:
            self._reprovisioning_repo = ReprovisioningRepository(session_maker=self.db.async_session_maker)
        return self._reprovisioning_repo

    @property
    def search_updates_repo(self) -> SearchUpdatesRepo:
        """The DB adapter to the search_updates table."""
        if not self._search_updates_repo:
            self._search_updates_repo = SearchUpdatesRepo(session_maker=self.db.async_session_maker)
        return self._search_updates_repo

    @property
    def search_reprovisioning(self) -> SearchReprovision:
        """The SearchReprovisioning class."""
        if not self._search_reprovisioning:
            self._search_reprovisioning = SearchReprovision(
                search_updates_repo=self.search_updates_repo,
                reprovisioning_repo=self.reprovisioning_repo,
                solr_config=self.solr_config,
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
                session_maker=self.db.async_session_maker,
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
                session_maker=self.db.async_session_maker,
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
                session_maker=self.db.async_session_maker,
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
                session_maker=self.db.async_session_maker,
                authz=self.authz,
                user_repo=self.kc_user_repo,
                secret_service_public_key=self.secrets_service_public_key,
            )
        return self._project_session_secret_repo

    @property
    def group_repo(self) -> GroupRepository:
        """The DB adapter for Renku groups."""
        if not self._group_repo:
            self._group_repo = GroupRepository(
                session_maker=self.db.async_session_maker,
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
                session_maker=self.db.async_session_maker,
                project_authz=self.authz,
                resource_pools=self.rp_repo,
                shipwright_client=self.builds_config.shipwright_client,
                builds_config=self.builds_config,
            )
        return self._session_repo

    @property
    def user_preferences_repo(self) -> UserPreferencesRepository:
        """The DB adapter for user preferences."""
        if not self._user_preferences_repo:
            self._user_preferences_repo = UserPreferencesRepository(
                session_maker=self.db.async_session_maker,
                user_preferences_config=self.user_preferences_config,
            )
        return self._user_preferences_repo

    @property
    def kc_user_repo(self) -> KcUserRepo:
        """The DB adapter for users."""
        if not self._kc_user_repo:
            self._kc_user_repo = KcUserRepo(
                session_maker=self.db.async_session_maker,
                message_queue=self.message_queue,
                event_repo=self.event_repo,
                group_repo=self.group_repo,
                search_updates_repo=self.search_updates_repo,
                encryption_key=self.encryption_key,
                authz=self.authz,
            )
        return self._kc_user_repo

    @property
    def user_secrets_repo(self) -> UserSecretsRepo:
        """The DB adapter for user secrets storage."""
        if not self._user_secrets_repo:
            low_level_user_secrets_repo = LowLevelUserSecretsRepo(
                session_maker=self.db.async_session_maker,
            )
            self._user_secrets_repo = UserSecretsRepo(
                session_maker=self.db.async_session_maker,
                low_level_repo=low_level_user_secrets_repo,
                user_repo=self.kc_user_repo,
                secret_service_public_key=self.secrets_service_public_key,
            )
        return self._user_secrets_repo

    @property
    def connected_services_repo(self) -> ConnectedServicesRepository:
        """The DB adapter for connected services."""
        if not self._connected_services_repo:
            self._connected_services_repo = ConnectedServicesRepository(
                session_maker=self.db.async_session_maker,
                encryption_key=self.encryption_key,
                async_oauth2_client_class=self.async_oauth2_client_class,
                internal_gitlab_url=self.gitlab_url,
            )
        return self._connected_services_repo

    @property
    def git_repositories_repo(self) -> GitRepositoriesRepository:
        """The DB adapter for repositories."""
        if not self._git_repositories_repo:
            self._git_repositories_repo = GitRepositoriesRepository(
                session_maker=self.db.async_session_maker,
                connected_services_repo=self.connected_services_repo,
                internal_gitlab_url=self.gitlab_url,
            )
        return self._git_repositories_repo

    @property
    def platform_repo(self) -> PlatformRepository:
        """The DB adapter for the platform configuration."""
        if not self._platform_repo:
            self._platform_repo = PlatformRepository(
                session_maker=self.db.async_session_maker,
            )
        return self._platform_repo

    @property
    def data_connector_repo(self) -> DataConnectorRepository:
        """The DB adapter for data connectors."""
        if not self._data_connector_repo:
            self._data_connector_repo = DataConnectorRepository(
                session_maker=self.db.async_session_maker,
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
                session_maker=self.db.async_session_maker,
                data_connector_repo=self.data_connector_repo,
                user_repo=self.kc_user_repo,
                secret_service_public_key=self.secrets_service_public_key,
                authz=self.authz,
            )
        return self._data_connector_secret_repo

    @classmethod
    def from_env(cls, prefix: str = "") -> "Config":
        """Create a config from environment variables."""

        user_store: base_models.UserStore
        authenticator: base_models.Authenticator
        gitlab_authenticator: base_models.Authenticator
        gitlab_client: base_models.GitlabAPIProtocol
        user_preferences_config: UserPreferencesConfig
        version = os.environ.get(f"{prefix}VERSION", "0.0.1")
        server_options_file = os.environ.get("NB_SERVER_OPTIONS__UI_CHOICES_PATH")
        server_defaults_file = os.environ.get("NB_SERVER_OPTIONS__DEFAULTS_PATH")
        k8s_namespace = os.environ.get("K8S_NAMESPACE", "default")
        max_pinned_projects = int(os.environ.get(f"{prefix}MAX_PINNED_PROJECTS", "10"))
        user_preferences_config = UserPreferencesConfig(max_pinned_projects=max_pinned_projects)
        db = DBConfig.from_env(prefix)
        solr_config = SolrClientConfig.from_env(prefix)
        kc_api: IKeycloakAPI
        secrets_service_public_key: PublicKeyTypes
        gitlab_url: str | None

        if os.environ.get(f"{prefix}DUMMY_STORES", "false").lower() == "true":
            encryption_key = secrets.token_bytes(32)
            secrets_service_public_key_path = os.getenv(f"{prefix}SECRETS_SERVICE_PUBLIC_KEY_PATH")
            if secrets_service_public_key_path is not None:
                secrets_service_public_key = serialization.load_pem_public_key(
                    Path(secrets_service_public_key_path).read_bytes()
                )
            else:
                private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
                secrets_service_public_key = private_key.public_key()

            authenticator = DummyAuthenticator()
            gitlab_authenticator = DummyAuthenticator()
            quota_repo = QuotaRepository(DummyCoreClient({}, {}), DummySchedulingClient({}), namespace=k8s_namespace)
            user_always_exists = os.environ.get("DUMMY_USERSTORE_USER_ALWAYS_EXISTS", "true").lower() == "true"
            user_store = DummyUserStore(user_always_exists=user_always_exists)
            gitlab_client = DummyGitlabAPI()
            dummy_users = [
                UnsavedUserInfo(id="user1", first_name="user1", last_name="doe", email="user1@doe.com"),
                UnsavedUserInfo(id="user2", first_name="user2", last_name="doe", email="user2@doe.com"),
            ]
            kc_api = DummyKeycloakAPI(users=[i._to_keycloak_dict() for i in dummy_users])
            redis = RedisConfig.fake()
            gitlab_url = None
        else:
            encryption_key_path = os.getenv(f"{prefix}ENCRYPTION_KEY_PATH", "/encryption-key")
            encryption_key = Path(encryption_key_path).read_bytes()
            secrets_service_public_key_path = os.getenv(
                f"{prefix}SECRETS_SERVICE_PUBLIC_KEY_PATH", "/secret_service_public_key"
            )
            secrets_service_public_key = serialization.load_pem_public_key(
                Path(secrets_service_public_key_path).read_bytes()
            )
            quota_repo = QuotaRepository(K8sCoreClient(), K8sSchedulingClient(), namespace=k8s_namespace)
            keycloak_url = os.environ.get(f"{prefix}KEYCLOAK_URL")
            if keycloak_url is None:
                raise errors.ConfigurationError(message="The Keycloak URL has to be specified.")
            keycloak_url = keycloak_url.rstrip("/")
            keycloak_realm = os.environ.get(f"{prefix}KEYCLOAK_REALM", "Renku")
            oidc_disc_data = oidc_discovery(keycloak_url, keycloak_realm)
            jwks_url = oidc_disc_data.get("jwks_uri")
            if jwks_url is None:
                raise errors.ConfigurationError(
                    message="The JWKS url for Keycloak cannot be found from the OIDC discovery endpoint."
                )
            algorithms = os.environ.get(f"{prefix}KEYCLOAK_TOKEN_SIGNATURE_ALGS")
            if algorithms is None:
                raise errors.ConfigurationError(message="At least one token signature algorithm is required.")
            algorithms_lst = [i.strip() for i in algorithms.split(",")]
            jwks = PyJWKClient(jwks_url)
            authenticator = KeycloakAuthenticator(jwks=jwks, algorithms=algorithms_lst)
            gitlab_url = os.environ.get(f"{prefix}GITLAB_URL")
            if gitlab_url is None:
                raise errors.ConfigurationError(message="Please provide the gitlab instance URL")
            gitlab_authenticator = GitlabAuthenticator(gitlab_url=gitlab_url)
            user_store = KcUserStore(keycloak_url=keycloak_url, realm=keycloak_realm)
            gitlab_client = GitlabAPI(gitlab_url=gitlab_url)
            client_id = os.environ[f"{prefix}KEYCLOAK_CLIENT_ID"]
            client_secret = os.environ[f"{prefix}KEYCLOAK_CLIENT_SECRET"]
            kc_api = KeycloakAPI(
                keycloak_url=keycloak_url,
                client_id=client_id,
                client_secret=client_secret,
                realm=keycloak_realm,
            )
            redis = RedisConfig.from_env(prefix)

        if not isinstance(secrets_service_public_key, rsa.RSAPublicKey):
            raise errors.ConfigurationError(message="Secret service public key is not an RSAPublicKey")

        sentry = SentryConfig.from_env(prefix)
        trusted_proxies = TrustedProxiesConfig.from_env(prefix)
        message_queue = RedisQueue(redis)
        nb_config = NotebooksConfig.from_env(db)
        builds_config = BuildsConfig.from_env(prefix, k8s_namespace)

        return cls(
            version=version,
            authenticator=authenticator,
            gitlab_authenticator=gitlab_authenticator,
            gitlab_client=gitlab_client,
            user_store=user_store,
            quota_repo=quota_repo,
            sentry=sentry,
            trusted_proxies=trusted_proxies,
            server_defaults_file=server_defaults_file,
            server_options_file=server_options_file,
            user_preferences_config=user_preferences_config,
            db=db,
            solr_config=solr_config,
            redis=redis,
            kc_api=kc_api,
            message_queue=message_queue,
            encryption_key=encryption_key,
            secrets_service_public_key=secrets_service_public_key,
            gitlab_url=gitlab_url,
            nb_config=nb_config,
            builds_config=builds_config,
        )
