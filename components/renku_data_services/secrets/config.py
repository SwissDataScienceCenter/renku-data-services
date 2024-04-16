"""Configurations."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt import PyJWKClient
from yaml import safe_load

import renku_data_services.secrets
from renku_data_services import base_models, errors
from renku_data_services.authn.dummy import DummyAuthenticator
from renku_data_services.authn.keycloak import KeycloakAuthenticator
from renku_data_services.db_config.config import DBConfig
from renku_data_services.k8s.client_interfaces import K8sCoreClientInterface
from renku_data_services.k8s.clients import DummyCoreClient, K8sCoreClient
from renku_data_services.secrets.db import UserSecretsRepo
from renku_data_services.utils.core import oidc_discovery


@dataclass
class Config:
    """Secrets service config."""

    db: DBConfig
    authenticator: base_models.Authenticator
    secrets_service_private_key: rsa.RSAPrivateKey
    core_client: K8sCoreClientInterface
    spec: dict[str, Any] = field(init=False, default_factory=dict)
    _user_secrets_repo: UserSecretsRepo | None = field(default=None, repr=False, init=False)

    def __post_init__(self):
        spec_file = Path(renku_data_services.secrets.__file__).resolve().parent / "api.spec.yaml"
        with open(spec_file) as f:
            self.spec = safe_load(f)

    @property
    def user_secrets_repo(self) -> UserSecretsRepo:
        """The DB adapter for users."""
        if not self._user_secrets_repo:
            self._user_secrets_repo = UserSecretsRepo(
                session_maker=self.db.async_session_maker,
            )
        return self._user_secrets_repo

    @classmethod
    def from_env(cls, prefix: str = ""):
        """Create a config from environment variables."""
        authenticator: base_models.Authenticator
        core_client: K8sCoreClientInterface
        db = DBConfig.from_env(prefix)
        secrets_service_private_key_path = os.getenv(
            f"{prefix}SECRETs_SERVICE_PRIVATE_KEY_PATH", "/secrets_service_private_key"
        )
        secrets_service_private_key = serialization.load_pem_private_key(
            Path(secrets_service_private_key_path).read_bytes(), password=None
        )
        if not isinstance(secrets_service_private_key, rsa.RSAPrivateKey):
            raise errors.ConfigurationError(message="Secret service private key is not an RSAPrivateKey")

        if os.environ.get(f"{prefix}DUMMY_STORES", "false").lower() == "true":
            authenticator = DummyAuthenticator()
            core_client = DummyCoreClient({}, {})
        else:
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
            core_client = K8sCoreClient()

        return cls(
            db=db,
            authenticator=authenticator,
            secrets_service_private_key=secrets_service_private_key,
            core_client=core_client,
        )
