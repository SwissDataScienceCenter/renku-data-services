"""Configurations."""
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
from jwt import PyJWKClient
from sqlalchemy.ext.asyncio import create_async_engine
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
class Config:
    """Configuration for the Data service."""

    user_repo: UserRepository
    rp_repo: ResourcePoolRepository
    storage_repo: StorageRepository
    user_preferences_repo: UserPreferencesRepository
    user_store: base_models.UserStore
    authenticator: base_models.Authenticator
    gitlab_authenticator: base_models.Authenticator
    quota_repo: QuotaRepository
    user_preferences_config: UserPreferencesConfig
    sync_db_connection_url: str = field(repr=False)
    spec: Dict[str, Any] = field(init=False, default_factory=dict)
    version: str = "0.0.1"
    app_name: str = "renku_crc"
    default_resource_pool_file: Optional[str] = None
    default_resource_pool: models.ResourcePool = default_resource_pool
    server_options_file: Optional[str] = None
    server_defaults_file: Optional[str] = None

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

    @classmethod
    def from_env(cls):
        """Create a config from environment variables."""

        prefix = ""
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

        max_pinned_projects = int(os.environ.get("MAX_PINNED_PROJECTS", "0"))
        user_preferences_config = UserPreferencesConfig(max_pinned_projects=max_pinned_projects)

        pg_host = os.environ.get("DB_HOST", "localhost")
        pg_user = os.environ.get("DB_USER", "renku")
        pg_port = os.environ.get("DB_PORT", "5432")
        db_name = os.environ.get("DB_NAME", "renku")
        pg_password = os.environ.get("DB_PASSWORD")
        if pg_password is None:
            raise errors.ConfigurationError(
                message="Please provide a database password in the 'DB_PASSWORD' environment variable."
            )
        async_engine = create_async_engine(
            f"postgresql+asyncpg://{pg_user}:{pg_password}@{pg_host}:{pg_port}/{db_name}",
            pool_size=10,
            max_overflow=0,
        )
        # NOTE: The synchrounous connection sqlalchemy URL is used only for migrations at startup
        sync_sqlalchemy_url = f"postgresql+psycopg://{pg_user}:{pg_password}@{pg_host}:{pg_port}/{db_name}"

        user_repo = UserRepository(engine=async_engine, quotas_repo=quota_repo)
        rp_repo = ResourcePoolRepository(
            engine=async_engine,
            quotas_repo=quota_repo,
        )
        storage_repo = StorageRepository(
            gitlab_client=gitlab_client,
            engine=async_engine,
        )
        user_preferences_repo = UserPreferencesRepository(
            user_preferences_config=user_preferences_config,
            engine=async_engine,
        )
        return cls(
            user_repo=user_repo,
            rp_repo=rp_repo,
            storage_repo=storage_repo,
            user_preferences_repo=user_preferences_repo,
            version=version,
            authenticator=authenticator,
            gitlab_authenticator=gitlab_authenticator,
            user_store=user_store,
            quota_repo=quota_repo,
            server_defaults_file=server_defaults_file,
            server_options_file=server_options_file,
            user_preferences_config=user_preferences_config,
            sync_db_connection_url=sync_sqlalchemy_url,
        )
