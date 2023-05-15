"""Configurations."""
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
from jwt import PyJWKClient
from tenacity import retry, stop_after_attempt, stop_after_delay, wait_fixed
from yaml import safe_load

import models
from db.adapter import ResourcePoolRepository, UserRepository
from models import errors
from users.credentials import KeycloakAuthenticator
from users.dummy import DummyAuthenticator, DummyUserStore
from users.keycloak import KcUserStore


@retry(stop=(stop_after_attempt(20) | stop_after_delay(300)), wait=wait_fixed(2), reraise=True)
def _oidc_discovery(url: str, realm: str) -> Dict[str, Any]:
    url = f"{url}/realms/{realm}/.well-known/openid-configuration"
    res = httpx.get(url)
    if res.status_code == 200:
        return res.json()
    raise errors.ConfigurationError(message=f"Cannot successfully do OIDC discovery with url {url}.")


default_resource_pool = models.ResourcePool(
    name="default",
    classes=set(
        [
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
        ]
    ),
    quota=None,
    public=True,
    default=True,
)


@dataclass
class Config:
    """Configuration for the CRAC service."""

    user_repo: UserRepository
    rp_repo: ResourcePoolRepository
    user_store: models.UserStore
    authenticator: models.Authenticator
    spec: Dict[str, Any] = field(init=False, default_factory=dict)
    version: str = "0.0.1"
    app_name: str = "renku_crac"
    default_resource_pool_file: Optional[str] = None
    default_resource_pool: models.ResourcePool = default_resource_pool

    def __post_init__(self):
        spec_file = Path(__file__).resolve().parent / "api.spec.yaml"
        with open(spec_file, "r") as f:
            self.spec = safe_load(f)
        if self.default_resource_pool_file is not None:
            with open(self.default_resource_pool_file, "r") as f:
                self.default_resource_pool = models.ResourcePool.from_dict(safe_load(f))

    @classmethod
    def from_env(cls):
        """Create a config from environment variables."""

        prefix = ""
        user_store: models.UserStore
        authenticator: models.Authenticator
        version = os.environ.get(f"{prefix}VERSION", "0.0.1")
        keycloak_url = None
        keycloak_realm = "Renku"

        if os.environ.get(f"{prefix}DUMMY_STORES", "false").lower() == "true":
            async_sqlalchemy_url = os.environ.get(
                f"{prefix}ASYNC_SQLALCHEMY_URL", "sqlite+aiosqlite:///data_services.db"
            )
            sync_sqlalchemy_url = os.environ.get(f"{prefix}SYNC_SQLALCHEMY_URL", "sqlite:///data_services.db")
            authenticator = DummyAuthenticator(admin=True)
            user_always_exists = os.environ.get("DUMMY_USERSTORE_USER_ALWAYS_EXISTS", "true").lower() == "true"
            user_store = DummyUserStore(user_always_exists=user_always_exists)
        else:
            pg_host = os.environ.get("DB_HOST", "localhost")
            pg_user = os.environ.get("DB_USER", "renku")
            pg_port = os.environ.get("DB_PORT", "5432")
            db_name = os.environ.get("DB_NAME", "renku")
            pg_password = os.environ.get("DB_PASSWORD")
            if pg_password is None:
                raise errors.ConfigurationError(
                    message="Please provide a database password in the 'DB_PASSWORD' environment variable."
                )
            async_sqlalchemy_url = f"postgresql+asyncpg://{pg_user}:{pg_password}@{pg_host}:{pg_port}/{db_name}"
            sync_sqlalchemy_url = f"postgresql+psycopg2://{pg_user}:{pg_password}@{pg_host}:{pg_port}/{db_name}"
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
                raise errors.ConfigurationError(message="At least one token signature algorithm is requried.")
            algorithms_lst = [i.strip() for i in algorithms.split(",")]
            jwks = PyJWKClient(jwks_url)
            authenticator = KeycloakAuthenticator(jwks=jwks, algorithms=algorithms_lst)
            user_store = KcUserStore(keycloak_url=keycloak_url, realm=keycloak_realm)

        user_repo = UserRepository(sync_sqlalchemy_url=sync_sqlalchemy_url, async_sqlalchemy_url=async_sqlalchemy_url)
        rp_repo = ResourcePoolRepository(
            sync_sqlalchemy_url=sync_sqlalchemy_url, async_sqlalchemy_url=async_sqlalchemy_url
        )
        return cls(
            user_repo=user_repo, rp_repo=rp_repo, version=version, authenticator=authenticator, user_store=user_store
        )
