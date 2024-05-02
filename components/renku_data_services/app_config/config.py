"""Configurations.

An important thing to note here is that the configuration classes in here
contain some getters (i.e. @property decorators) intentionally. This is done for
things that need a database connection and the purpose is that the database connection
is not initialized when the classes are initialized. Only if the properties that need
the database will instantiate a connection when they are used. And even in this case
a single connection will be reused. This allows for the configuration classes to be
instantiated multiple times without creating multiple database connections.
"""

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from authlib.integrations.httpx_client import AsyncOAuth2Client
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.types import PublicKeyTypes
from jwt import PyJWKClient
from yaml import safe_load

import renku_data_services.base_models as base_models
import renku_data_services.connected_services
import renku_data_services.crc
import renku_data_services.storage
import renku_data_services.user_preferences
import renku_data_services.users
from renku_data_services import errors
from renku_data_services.authn.dummy import DummyAuthenticator, DummyUserStore
from renku_data_services.authn.gitlab import GitlabAuthenticator
from renku_data_services.authn.keycloak import KcUserStore, KeycloakAuthenticator
from renku_data_services.authz.authz import Authz
from renku_data_services.authz.config import AuthzConfig
from renku_data_services.connected_services.db import ConnectedServicesRepository
from renku_data_services.crc import models
from renku_data_services.crc.db import ResourcePoolRepository, UserRepository
from renku_data_services.data_api.server_options import (
    ServerOptions,
    ServerOptionsDefaults,
    generate_default_resource_pool,
)
from renku_data_services.db_config import DBConfig
from renku_data_services.git.gitlab import DummyGitlabAPI, GitlabAPI
from renku_data_services.k8s.clients import DummyCoreClient, DummySchedulingClient, K8sCoreClient, K8sSchedulingClient
from renku_data_services.k8s.quota import QuotaRepository
from renku_data_services.message_queue.config import RedisConfig
from renku_data_services.message_queue.db import EventRepository
from renku_data_services.message_queue.interface import IMessageQueue
from renku_data_services.message_queue.redis_queue import RedisQueue
from renku_data_services.namespace.db import GroupRepository
from renku_data_services.project.db import ProjectMemberRepository, ProjectRepository
from renku_data_services.secrets.db import UserSecretsRepo
from renku_data_services.session.db import SessionRepository
from renku_data_services.storage.db import StorageRepository, StorageV2Repository
from renku_data_services.user_preferences.config import UserPreferencesConfig
from renku_data_services.user_preferences.db import UserPreferencesRepository
from renku_data_services.users.db import UserRepo as KcUserRepo
from renku_data_services.users.dummy_kc_api import DummyKeycloakAPI
from renku_data_services.users.kc_api import IKeycloakAPI, KeycloakAPI
from renku_data_services.users.models import UserInfo
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
    def from_env(cls, prefix: str = ""):
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
    def from_env(cls, prefix: str = ""):
        """Create a config from environment variables."""
        proxies_count = int(os.environ.get(f"{prefix}PROXIES_COUNT") or "0")
        real_ip_header = os.environ.get(f"{prefix}REAL_IP_HEADER")
        return cls(proxies_count=proxies_count or None, real_ip_header=real_ip_header or None)


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

    secrets_service_public_key: rsa.RSAPublicKey
    """The public key of the secrets service, used to encrypt user secrets that only it can decrypt."""
    encryption_key: bytes = field(repr=False)
    """The encryption key to encrypt user keys at rest in the database."""

    authz_config: AuthzConfig = field(default_factory=lambda: AuthzConfig.from_env())
    spec: dict[str, Any] = field(init=False, default_factory=dict)
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
    _storage_v2_repo: StorageV2Repository | None = field(default=None, repr=False, init=False)
    _project_repo: ProjectRepository | None = field(default=None, repr=False, init=False)
    _group_repo: GroupRepository | None = field(default=None, repr=False, init=False)
    _event_repo: EventRepository | None = field(default=None, repr=False, init=False)
    _session_repo: SessionRepository | None = field(default=None, repr=False, init=False)
    _user_preferences_repo: UserPreferencesRepository | None = field(default=None, repr=False, init=False)
    _kc_user_repo: KcUserRepo | None = field(default=None, repr=False, init=False)
    _user_secrets_repo: UserSecretsRepo | None = field(default=None, repr=False, init=False)
    _project_member_repo: ProjectMemberRepository | None = field(default=None, repr=False, init=False)
    _connected_services_repo: ConnectedServicesRepository | None = field(default=None, repr=False, init=False)

    def __post_init__(self):
        spec_file = Path(renku_data_services.crc.__file__).resolve().parent / "api.spec.yaml"
        with open(spec_file) as f:
            crc_spec = safe_load(f)

        spec_file = Path(renku_data_services.storage.__file__).resolve().parent / "api.spec.yaml"
        with open(spec_file) as f:
            storage_spec = safe_load(f)

        spec_file = Path(renku_data_services.user_preferences.__file__).resolve().parent / "api.spec.yaml"
        with open(spec_file) as f:
            user_preferences_spec = safe_load(f)

        spec_file = Path(renku_data_services.users.__file__).resolve().parent / "api.spec.yaml"
        with open(spec_file) as f:
            users = safe_load(f)

        spec_file = Path(renku_data_services.project.__file__).resolve().parent / "api.spec.yaml"
        with open(spec_file) as f:
            projects = safe_load(f)

        spec_file = Path(renku_data_services.namespace.__file__).resolve().parent / "api.spec.yaml"
        with open(spec_file) as f:
            groups = safe_load(f)

        spec_file = Path(renku_data_services.session.__file__).resolve().parent / "api.spec.yaml"
        with open(spec_file) as f:
            sessions = safe_load(f)

        spec_file = Path(renku_data_services.connected_services.__file__).resolve().parent / "api.spec.yaml"
        with open(spec_file) as f:
            connected_services = safe_load(f)

        self.spec = merge_api_specs(
            crc_spec, storage_spec, user_preferences_spec, users, projects, groups, sessions, connected_services
        )

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
        """The DB adapter for users."""
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
                session_maker=self.db.async_session_maker, gitlab_client=self.gitlab_client
            )
        return self._storage_repo

    @property
    def storage_v2_repo(self) -> StorageV2Repository:
        """The DB adapter for V2 cloud storage configs."""
        if not self._storage_v2_repo:
            self._storage_v2_repo = StorageV2Repository(
                session_maker=self.db.async_session_maker, project_authz=self.authz
            )
        return self._storage_v2_repo

    @property
    def event_repo(self) -> EventRepository:
        """The DB adapter for cloud event configs."""
        if not self._event_repo:
            self._event_repo = EventRepository(
                session_maker=self.db.async_session_maker, message_queue=self.message_queue
            )
        return self._event_repo

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
            )
        return self._project_repo

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
    def group_repo(self) -> GroupRepository:
        """The DB adapter for Renku groups."""
        if not self._group_repo:
            self._group_repo = GroupRepository(
                session_maker=self.db.async_session_maker,
                event_repo=self.event_repo,
                group_authz=self.authz,
                message_queue=self.message_queue,
            )
        return self._group_repo

    @property
    def session_repo(self) -> SessionRepository:
        """The DB adapter for sessions."""
        if not self._session_repo:
            self._session_repo = SessionRepository(session_maker=self.db.async_session_maker, project_authz=self.authz)
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
                encryption_key=self.encryption_key,
                authz=self.authz,
            )
        return self._kc_user_repo

    @property
    def user_secrets_repo(self) -> UserSecretsRepo:
        """The DB adapter for user secrets storage."""
        if not self._user_secrets_repo:
            self._user_secrets_repo = UserSecretsRepo(
                session_maker=self.db.async_session_maker,
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
            )
        return self._connected_services_repo

    @classmethod
    def from_env(cls, prefix: str = ""):
        """Create a config from environment variables."""

        user_store: base_models.UserStore
        authenticator: base_models.Authenticator
        gitlab_authenticator: base_models.Authenticator
        gitlab_client: base_models.GitlabAPIProtocol
        user_preferences_config: UserPreferencesConfig
        version = os.environ.get(f"{prefix}VERSION", "0.0.1")
        server_options_file = os.environ.get("SERVER_OPTIONS")
        server_defaults_file = os.environ.get("SERVER_DEFAULTS")
        k8s_namespace = os.environ.get("K8S_NAMESPACE", "default")
        max_pinned_projects = int(os.environ.get(f"{prefix}MAX_PINNED_PROJECTS", "10"))
        user_preferences_config = UserPreferencesConfig(max_pinned_projects=max_pinned_projects)
        db = DBConfig.from_env(prefix)
        kc_api: IKeycloakAPI
        secrets_service_public_key: PublicKeyTypes

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
                UserInfo("user1", "user1", "doe", "user1@doe.com"),
                UserInfo("user2", "user2", "doe", "user2@doe.com"),
            ]
            kc_api = DummyKeycloakAPI(users=[i._to_keycloak_dict() for i in dummy_users])
            redis = RedisConfig.fake()
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
            redis=redis,
            kc_api=kc_api,
            message_queue=message_queue,
            encryption_key=encryption_key,
            secrets_service_public_key=secrets_service_public_key,
        )
