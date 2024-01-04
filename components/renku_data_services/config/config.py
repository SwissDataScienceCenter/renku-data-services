"""
Configurations.

An important thing to note here is that the configuration classes in here
contain some getters (i.e. @property decorators) intentionally. This is done for
things that need a database connection and the purpose is that the database connection
is not initialized when the classes are initialized. Only if the properties that need
the database will instantiate a connection when they are used. And even in this case
a single connection will be reused. This allows for the configuration classes to be
instantiated multiple times without creating multiple database connections.
"""
import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, ClassVar, Dict, Optional

import httpx
from jwt import PyJWKClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from tenacity import retry, stop_after_attempt, stop_after_delay, wait_fixed
from yaml import safe_load

import renku_data_services.base_models as base_models
import renku_data_services.crc
import renku_data_services.storage
import renku_data_services.user_preferences
from renku_data_services import errors
from renku_data_services.authn.dummy import DummyAuthenticator, DummyUserStore
from renku_data_services.authn.gitlab import GitlabAuthenticator
from renku_data_services.authn.keycloak import KcUserStore, KeycloakAuthenticator
from renku_data_services.crc import models
from renku_data_services.crc.db import ResourcePoolRepository, UserRepository
from renku_data_services.data_api.server_options import (
    ServerOptions,
    ServerOptionsDefaults,
    generate_default_resource_pool,
)
from renku_data_services.git.gitlab import DummyGitlabAPI, GitlabAPI
from renku_data_services.k8s.clients import DummyCoreClient, DummySchedulingClient, K8sCoreClient, K8sSchedulingClient
from renku_data_services.k8s.quota import QuotaRepository
from renku_data_services.storage.db import StorageRepository
from renku_data_services.user_preferences.db import UserPreferencesRepository
from renku_data_services.utils.core import get_ssl_context, merge_api_specs
from renku_data_services.user_preferences.config import UserPreferencesConfig


@retry(stop=(stop_after_attempt(20) | stop_after_delay(300)), wait=wait_fixed(2), reraise=True)
def _oidc_discovery(url: str, realm: str) -> Dict[str, Any]:
    url = f"{url}/realms/{realm}/.well-known/openid-configuration"
    res = httpx.get(url, verify=get_ssl_context())
    if res.status_code == 200:
        return res.json()
    raise errors.ConfigurationError(message=f"Cannot successfully do OIDC discovery with url {url}.")


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
class DBConfig:
    """Database configuration."""

    password: str = field(repr=False)
    host: str = "localhost"
    user: str = "renku"
    port: str = "5432"
    db_name: str = "renku"
    _async_engine: ClassVar[AsyncEngine | None] = field(default=None, repr=False, init=False)

    @classmethod
    def from_env(cls, prefix: str = ""):
        """Create a database configuration from environment variables."""

        pg_host = os.environ.get(f"{prefix}DB_HOST")
        pg_user = os.environ.get(f"{prefix}DB_USER")
        pg_port = os.environ.get(f"{prefix}DB_PORT")
        db_name = os.environ.get(f"{prefix}DB_NAME")
        pg_password = os.environ.get(f"{prefix}DB_PASSWORD")
        if pg_password is None:
            raise errors.ConfigurationError(
                message=f"Please provide a database password in the '{prefix}DB_PASSWORD' environment variable."
            )
        kwargs = {"host": pg_host, "password": pg_password, "port": pg_port, "db_name": db_name, "user": pg_user}
        return cls(**{k: v for (k, v) in kwargs.items() if v is not None})

    def conn_url(self, async_client: bool = True) -> str:
        """Return an asynchronous or synchronous database connection url."""
        if async_client:
            return f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.db_name}"
        return f"postgresql+psycopg://{self.user}:{self.password}@{self.host}:{self.port}/{self.db_name}"

    @property
    def async_session_maker(self) -> Callable[..., AsyncSession]:
        """The asynchronous DB engine."""
        if not DBConfig._async_engine:
            DBConfig._async_engine = create_async_engine(
                self.conn_url(),
                pool_size=10,
                max_overflow=0,
            )
        return async_sessionmaker(DBConfig._async_engine, expire_on_commit=False)

    @staticmethod
    def dispose_connection():
        """Dispose of the main database connection pool."""

        if DBConfig._async_engine:
            asyncio.get_event_loop().run_until_complete(DBConfig._async_engine.dispose())


@dataclass
class Config:
    """Configuration for the Data service."""

    user_store: base_models.UserStore
    authenticator: base_models.Authenticator
    gitlab_authenticator: base_models.Authenticator
    quota_repo: QuotaRepository
    user_preferences_config: UserPreferencesConfig
    db: DBConfig
    gitlab_client: base_models.GitlabAPIProtocol
    spec: Dict[str, Any] = field(init=False, default_factory=dict)
    version: str = "0.0.1"
    app_name: str = "renku_crc"
    default_resource_pool_file: Optional[str] = None
    default_resource_pool: models.ResourcePool = default_resource_pool
    server_options_file: Optional[str] = None
    server_defaults_file: Optional[str] = None
    _user_repo: UserRepository | None = field(default=None, repr=False, init=False)
    _rp_repo: ResourcePoolRepository | None = field(default=None, repr=False, init=False)
    _storage_repo: StorageRepository | None = field(default=None, repr=False, init=False)
    _user_preferences_repo: UserPreferencesRepository | None = field(default=None, repr=False, init=False)

    def __post_init__(self):
        spec_file = Path(renku_data_services.crc.__file__).resolve().parent / "api.spec.yaml"
        with open(spec_file, "r") as f:
            crc_spec = safe_load(f)

        spec_file = Path(renku_data_services.storage.__file__).resolve().parent / "api.spec.yaml"
        with open(spec_file, "r") as f:
            storage_spec = safe_load(f)

        spec_file = Path(renku_data_services.user_preferences.__file__).resolve().parent / "api.spec.yaml"
        with open(spec_file, "r") as f:
            user_preferences_spec = safe_load(f)

        self.spec = merge_api_specs(crc_spec, storage_spec, user_preferences_spec)

        if self.default_resource_pool_file is not None:
            with open(self.default_resource_pool_file, "r") as f:
                self.default_resource_pool = models.ResourcePool.from_dict(safe_load(f))
        if self.server_defaults_file is not None and self.server_options_file is not None:
            with open(self.server_options_file, "r") as f:
                options = ServerOptions.model_validate(safe_load(f))
            with open(self.server_defaults_file, "r") as f:
                defaults = ServerOptionsDefaults.model_validate(safe_load(f))
            self.default_resource_pool = generate_default_resource_pool(options, defaults)

    @property
    def user_repo(self) -> UserRepository:
        """The DB adapter for users."""
        if not self._user_repo:
            self._user_repo = UserRepository(session_maker=self.db.async_session_maker, quotas_repo=self.quota_repo)
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
        """The DB adapter for cloud storage configs."""
        if not self._storage_repo:
            self._storage_repo = StorageRepository(
                session_maker=self.db.async_session_maker, gitlab_client=self.gitlab_client
            )
        return self._storage_repo

    @property
    def user_preferences_repo(self) -> UserPreferencesRepository:
        """The DB adapter for user preferences."""
        if not self._user_preferences_repo:
            self._user_preferences_repo = UserPreferencesRepository(
                session_maker=self.db.async_session_maker,
                user_preferences_config=self.user_preferences_config,
            )
        return self._user_preferences_repo

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
        gitlab_url = None
        max_pinned_projects = int(os.environ.get(f"{prefix}MAX_PINNED_PROJECTS", "10"))
        user_preferences_config = UserPreferencesConfig(max_pinned_projects=max_pinned_projects)
        db = DBConfig.from_env(prefix)

        if os.environ.get(f"{prefix}DUMMY_STORES", "false").lower() == "true":
            authenticator = DummyAuthenticator()
            gitlab_authenticator = DummyAuthenticator()
            quota_repo = QuotaRepository(DummyCoreClient({}), DummySchedulingClient({}), namespace=k8s_namespace)
            user_always_exists = os.environ.get("DUMMY_USERSTORE_USER_ALWAYS_EXISTS", "true").lower() == "true"
            user_store = DummyUserStore(user_always_exists=user_always_exists)
            gitlab_client = DummyGitlabAPI()
        else:
            quota_repo = QuotaRepository(K8sCoreClient(), K8sSchedulingClient(), namespace=k8s_namespace)
            keycloak_url = os.environ.get(f"{prefix}KEYCLOAK_URL")
            if keycloak_url is None:
                raise errors.ConfigurationError(message="The Keycloak URL has to be specified.")
            keycloak_url = keycloak_url.rstrip("/")
            keycloak_realm = os.environ.get(f"{prefix}KEYCLOAK_REALM", "Renku")
            oidc_disc_data = _oidc_discovery(keycloak_url, keycloak_realm)
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

        return cls(
            version=version,
            authenticator=authenticator,
            gitlab_authenticator=gitlab_authenticator,
            gitlab_client=gitlab_client,
            user_store=user_store,
            quota_repo=quota_repo,
            server_defaults_file=server_defaults_file,
            server_options_file=server_options_file,
            user_preferences_config=user_preferences_config,
            db=db,
        )