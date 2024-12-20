"""Configurations."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.types import PrivateKeyTypes
from jwt import PyJWKClient
from yaml import safe_load

import renku_data_services.secrets
from renku_data_services import base_models, errors
from renku_data_services.authn.dummy import DummyAuthenticator
from renku_data_services.authn.keycloak import KeycloakAuthenticator
from renku_data_services.db_config.config import DBConfig
from renku_data_services.k8s.client_interfaces import K8sCoreClientInterface
from renku_data_services.k8s.clients import DummyCoreClient, K8sCoreClient
from renku_data_services.secrets.db import LowLevelUserSecretsRepo
from renku_data_services.utils.core import oidc_discovery


@dataclass
class Config:
    """Secrets service config."""

    db: DBConfig
    authenticator: base_models.Authenticator
    secrets_service_private_key: rsa.RSAPrivateKey
    previous_secrets_service_private_key: rsa.RSAPrivateKey | None
    core_client: K8sCoreClientInterface
    app_name: str = "secrets_storage"
    version: str = "0.0.1"
    spec: dict[str, Any] = field(init=False, default_factory=dict)
    _user_secrets_repo: LowLevelUserSecretsRepo | None = field(default=None, repr=False, init=False)

    def __post_init__(self) -> None:
        spec_file = Path(renku_data_services.secrets.__file__).resolve().parent / "api.spec.yaml"
        with open(spec_file) as f:
            self.spec = safe_load(f)

    @property
    def user_secrets_repo(self) -> LowLevelUserSecretsRepo:
        """The DB adapter for users."""
        if not self._user_secrets_repo:
            self._user_secrets_repo = LowLevelUserSecretsRepo(
                session_maker=self.db.async_session_maker,
            )
        return self._user_secrets_repo

    @classmethod
    def from_env(cls, prefix: str = "") -> "Config":
        """Create a config from environment variables."""
        authenticator: base_models.Authenticator
        core_client: K8sCoreClientInterface
        secrets_service_private_key: PrivateKeyTypes
        previous_secrets_service_private_key: PrivateKeyTypes | None = None
        db = DBConfig.from_env(prefix)

        version = os.environ.get(f"{prefix}VERSION", "0.0.1")

        if os.environ.get(f"{prefix}DUMMY_STORES", "false").lower() == "true":
            authenticator = DummyAuthenticator()
            core_client = DummyCoreClient({}, {})
            secrets_service_private_key_path = os.getenv(f"{prefix}SECRETS_SERVICE_PRIVATE_KEY_PATH")
            if secrets_service_private_key_path:
                secrets_service_private_key = serialization.load_pem_private_key(
                    Path(secrets_service_private_key_path).read_bytes(), password=None
                )
            else:
                secrets_service_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            previous_secrets_service_private_key_path = os.getenv(f"{prefix}PREVIOUS_SECRETS_SERVICE_PRIVATE_KEY_PATH")
            if previous_secrets_service_private_key_path:
                previous_private_key = Path(previous_secrets_service_private_key_path).read_bytes()
                if previous_private_key is not None and len(previous_private_key) > 0:
                    previous_secrets_service_private_key = serialization.load_pem_private_key(
                        previous_private_key, password=None
                    )
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
            secrets_service_private_key_path = os.getenv(
                f"{prefix}SECRETS_SERVICE_PRIVATE_KEY_PATH", "/secrets_service_private_key"
            )
            secrets_service_private_key = serialization.load_pem_private_key(
                Path(secrets_service_private_key_path).read_bytes(), password=None
            )
            previous_secrets_service_private_key_path = os.getenv(f"{prefix}PREVIOUS_SECRETS_SERVICE_PRIVATE_KEY_PATH")
            if previous_secrets_service_private_key_path and Path(previous_secrets_service_private_key_path).exists():
                previous_secrets_service_private_key = serialization.load_pem_private_key(
                    Path(previous_secrets_service_private_key_path).read_bytes(), password=None
                )
        if not isinstance(secrets_service_private_key, rsa.RSAPrivateKey):
            raise errors.ConfigurationError(message="Secret service private key is not an RSAPrivateKey")

        if previous_secrets_service_private_key is not None and not isinstance(
            previous_secrets_service_private_key, rsa.RSAPrivateKey
        ):
            raise errors.ConfigurationError(message="Old secret service private key is not an RSAPrivateKey")

        return cls(
            version=version,
            db=db,
            authenticator=authenticator,
            secrets_service_private_key=secrets_service_private_key,
            previous_secrets_service_private_key=previous_secrets_service_private_key,
            core_client=core_client,
        )
