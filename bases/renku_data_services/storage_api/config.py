"""Configurations."""
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict

import httpx
import renku_data_services.base_models as base_models
import renku_data_services.storage_schemas
from jwt import PyJWKClient
from renku_data_services.storage_adapters import StorageRepository
from renku_data_services.users.credentials import KeycloakAuthenticator
from renku_data_services.users.dummy import DummyAuthenticator
from tenacity import retry, stop_after_attempt, stop_after_delay, wait_fixed
from yaml import safe_load

from renku_data_services import errors


@retry(stop=(stop_after_attempt(20) | stop_after_delay(300)), wait=wait_fixed(2), reraise=True)
def _oidc_discovery(url: str, realm: str) -> Dict[str, Any]:
    url = f"{url}/realms/{realm}/.well-known/openid-configuration"
    res = httpx.get(url)
    if res.status_code == 200:
        return res.json()
    raise errors.ConfigurationError(message=f"Cannot successfully do OIDC discovery with url {url}.")


@dataclass
class Config:
    """Configuration for the Cloud Storage service."""

    storage_repo: StorageRepository
    authenticator: base_models.Authenticator
    spec: Dict[str, Any] = field(init=False, default_factory=dict)
    version: str = "0.0.1"
    app_name: str = "renku_storage"

    def __post_init__(self):
        spec_file = Path(renku_data_services.storage_schemas.__file__).resolve().parent / "api.spec.yaml"
        with open(spec_file, "r") as f:
            self.spec = safe_load(f)

    @classmethod
    def from_env(cls):
        """Create a config from environment variables."""

        prefix = ""
        authenticator: base_models.Authenticator
        version = os.environ.get(f"{prefix}VERSION", "0.0.1")
        keycloak_url = None
        keycloak_realm = "Renku"

        if os.environ.get(f"{prefix}DUMMY_STORES", "false").lower() == "true":
            async_sqlalchemy_url = os.environ.get(
                f"{prefix}ASYNC_SQLALCHEMY_URL", "sqlite+aiosqlite:///data_services.db"
            )
            sync_sqlalchemy_url = os.environ.get(f"{prefix}SYNC_SQLALCHEMY_URL", "sqlite:///data_services.db")
            authenticator = DummyAuthenticator(admin=True)
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

        storage_repo = StorageRepository(
            sync_sqlalchemy_url=sync_sqlalchemy_url, async_sqlalchemy_url=async_sqlalchemy_url
        )
        return cls(
            storage_repo=storage_repo,
            version=version,
            authenticator=authenticator,
        )
