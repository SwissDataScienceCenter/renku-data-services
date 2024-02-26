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

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
import urllib3
from jwt import PyJWKClient
from tenacity import retry, stop_after_attempt, stop_after_delay, wait_fixed
from yaml import safe_load

import renku_data_services.base_models as base_models
import renku_data_services.crc
import renku_data_services.storage
import renku_data_services.user_preferences
import renku_data_services.users
from renku_data_services import errors
from renku_data_services.authn.dummy import DummyAuthenticator, DummyUserStore
from renku_data_services.authn.gitlab import GitlabAuthenticator
from renku_data_services.authn.keycloak import KcUserStore, KeycloakAuthenticator
from renku_data_services.authz.authz import IProjectAuthorizer, SQLProjectAuthorizer
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
from renku_data_services.project.db import ProjectMemberRepository, ProjectRepository
from renku_data_services.session.config import SessionConfig
from renku_data_services.session.db import SessionRepository
from renku_data_services.storage.db import StorageRepository
from renku_data_services.user_preferences.config import UserPreferencesConfig
from renku_data_services.user_preferences.db import UserPreferencesRepository
from renku_data_services.users.db import UserRepo as KcUserRepo
from renku_data_services.users.dummy_kc_api import DummyKeycloakAPI
from renku_data_services.users.kc_api import IKeycloakAPI, KeycloakAPI
from renku_data_services.utils.core import get_ssl_context, merge_api_specs


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

    user_store: base_models.UserStore
    authenticator: base_models.Authenticator
    gitlab_authenticator: base_models.Authenticator
    quota_repo: QuotaRepository
    user_preferences_config: UserPreferencesConfig
    db: DBConfig
    gitlab_client: base_models.GitlabAPIProtocol
    kc_api: IKeycloakAPI
    spec: Dict[str, Any] = field(init=False, default_factory=dict)
    version: str = "0.0.1"
    app_name: str = "renku_crc"
    default_resource_pool_file: Optional[str] = None
    default_resource_pool: models.ResourcePool = default_resource_pool
    session_config: SessionConfig | None = field(default=None)
    server_options_file: Optional[str] = None
    server_defaults_file: Optional[str] = None
    _user_repo: UserRepository | None = field(default=None, repr=False, init=False)
    _rp_repo: ResourcePoolRepository | None = field(default=None, repr=False, init=False)
    _storage_repo: StorageRepository | None = field(default=None, repr=False, init=False)
    _project_repo: ProjectRepository | None = field(default=None, repr=False, init=False)
    _project_authz: IProjectAuthorizer | None = field(default=None, repr=False, init=False)
    _session_repo: SessionRepository | None = field(default=None, repr=False, init=False)
    _user_preferences_repo: UserPreferencesRepository | None = field(default=None, repr=False, init=False)
    _kc_user_repo: KcUserRepo | None = field(default=None, repr=False, init=False)
    _project_member_repo: ProjectMemberRepository | None = field(default=None, repr=False, init=False)

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

        spec_file = Path(renku_data_services.users.__file__).resolve().parent / "api.spec.yaml"
        with open(spec_file, "r") as f:
            users = safe_load(f)

        spec_file = Path(renku_data_services.project.__file__).resolve().parent / "api.spec.yaml"
        with open(spec_file, "r") as f:
            projects = safe_load(f)

        spec_file = Path(renku_data_services.session.__file__).resolve().parent / "api.spec.yaml"
        with open(spec_file, "r") as f:
            sessions = safe_load(f)

        self.spec = merge_api_specs(crc_spec, storage_spec, user_preferences_spec, users, projects, sessions)

        notebooks_url = _get_notebooks_url_from_keycloak_url(self.kc_api.keycloak_url)  # type: ignore
        self.session_config = SessionConfig(notebooks_url=notebooks_url)

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
    def project_repo(self) -> ProjectRepository:
        """The DB adapter for Renku native projects."""
        if not self._project_repo:
            self._project_repo = ProjectRepository(
                session_maker=self.db.async_session_maker, project_authz=self.project_authz
            )
        return self._project_repo

    @property
    def project_member_repo(self) -> ProjectMemberRepository:
        """The DB adapter for Renku native projects members."""
        if not self._project_member_repo:
            self._project_member_repo = ProjectMemberRepository(
                session_maker=self.db.async_session_maker, project_authz=self.project_authz
            )
        return self._project_member_repo

    @property
    def project_authz(self) -> IProjectAuthorizer:
        """The DB adapter for authorization."""
        if not self._project_authz:
            self._project_authz = SQLProjectAuthorizer(session_maker=self.db.async_session_maker)
        return self._project_authz

    @property
    def session_repo(self) -> SessionRepository:
        """The DB adapter for sessions."""
        if not self._session_repo:
            self._session_repo = SessionRepository(
                session_maker=self.db.async_session_maker,
                project_authz=self.project_authz,
                session_config=self.session_config,
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
            self._kc_user_repo = KcUserRepo(session_maker=self.db.async_session_maker)
        return self._kc_user_repo

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
        gitlab_url: Optional[str]
        max_pinned_projects = int(os.environ.get(f"{prefix}MAX_PINNED_PROJECTS", "10"))
        user_preferences_config = UserPreferencesConfig(max_pinned_projects=max_pinned_projects)
        db = DBConfig.from_env(prefix)
        kc_api: IKeycloakAPI
        session_config: SessionConfig

        if os.environ.get(f"{prefix}DUMMY_STORES", "false").lower() == "true":
            authenticator = DummyAuthenticator()
            gitlab_authenticator = DummyAuthenticator()
            quota_repo = QuotaRepository(DummyCoreClient({}), DummySchedulingClient({}), namespace=k8s_namespace)
            user_always_exists = os.environ.get("DUMMY_USERSTORE_USER_ALWAYS_EXISTS", "true").lower() == "true"
            user_store = DummyUserStore(user_always_exists=user_always_exists)
            gitlab_client = DummyGitlabAPI()
            kc_api = DummyKeycloakAPI()
            session_config = SessionConfig(notebooks_url="")
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
            session_config = SessionConfig(notebooks_url=_get_notebooks_url_from_keycloak_url(keycloak_url))
            client_id = os.environ[f"{prefix}KEYCLOAK_CLIENT_ID"]
            client_secret = os.environ[f"{prefix}KEYCLOAK_CLIENT_SECRET"]
            kc_api = KeycloakAPI(
                keycloak_url=keycloak_url,
                client_id=client_id,
                client_secret=client_secret,
                realm=keycloak_realm,
            )

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
            kc_api=kc_api,
            session_config=session_config,
        )


def _get_notebooks_url_from_keycloak_url(keycloak_url) -> str:
    parsed_url = urllib3.parse.urlparse(keycloak_url)  # type: ignore
    return parsed_url._replace(path="notebooks").geturl()
