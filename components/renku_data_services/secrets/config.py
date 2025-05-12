"""Configurations."""

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Self

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.types import PrivateKeyTypes
from jwt import PyJWKClient
from yaml import safe_load

import renku_data_services.secrets
from renku_data_services import base_models, errors
from renku_data_services.app_config.config import KeycloakConfig
from renku_data_services.authn.dummy import DummyAuthenticator
from renku_data_services.authn.keycloak import KeycloakAuthenticator
from renku_data_services.db_config.config import DBConfig
from renku_data_services.k8s.client_interfaces import K8sCoreClientInterface
from renku_data_services.k8s.clients import DummyCoreClient, K8sCoreClient
from renku_data_services.secrets.db import LowLevelUserSecretsRepo
from renku_data_services.utils.core import oidc_discovery


@dataclass
class PublicSecretsConfig:
    """Configuration class for secrets settings."""

    public_key: rsa.RSAPublicKey
    encryption_key: bytes = field(repr=False)

    @classmethod
    def from_env(cls) -> Self:
        """Load config from environment variables."""
        if os.environ.get("DUMMY_STORES", "false").lower() == "true":
            public_key_path = os.getenv("SECRETS_SERVICE_PUBLIC_KEY_PATH")
            encryption_key = secrets.token_bytes(32)
            if public_key_path is not None:
                public_key = serialization.load_pem_public_key(Path(public_key_path).read_bytes())
            else:
                # generate new random key
                private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
                public_key = private_key.public_key()
        else:
            public_key_path = os.getenv("SECRETS_SERVICE_PUBLIC_KEY_PATH", "/secret_service_public_key")
            encryption_key_path = os.getenv("ENCRYPTION_KEY_PATH", "encryption_key")
            encryption_key = Path(encryption_key_path).read_bytes()
            public_key_path = os.getenv("SECRETS_SERVICE_PUBLIC_KEY_PATH", "/secret_service_public_key")
            public_key = serialization.load_pem_public_key(Path(public_key_path).read_bytes())
        if not isinstance(public_key, rsa.RSAPublicKey):
            raise errors.ConfigurationError(message="Secret service public key is not an RSAPublicKey")

        return cls(
            public_key=public_key,
            encryption_key=encryption_key,
        )


@dataclass
class PrivateSecretsConfig:
    """Private configuration for the secrets service.

    IMPORTANT: To only be used inside secrets service.
    """

    private_key: rsa.RSAPrivateKey
    previous_private_key: rsa.RSAPrivateKey | None

    @classmethod
    def from_env(cls) -> Self:
        """Load config from environment."""
        previous_private_key: PrivateKeyTypes | None = None
        if os.environ.get("DUMMY_STORES", "false").lower() == "true":
            private_key_path = os.getenv("SECRETS_SERVICE_PRIVATE_KEY_PATH")
            if private_key_path:
                private_key = serialization.load_pem_private_key(Path(private_key_path).read_bytes(), password=None)
            else:
                private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            previous_secrets_service_private_key_path = os.getenv("PREVIOUS_SECRETS_SERVICE_PRIVATE_KEY_PATH")
            if previous_secrets_service_private_key_path:
                previous_private_key_content = Path(previous_secrets_service_private_key_path).read_bytes()
                if previous_private_key_content is not None and len(previous_private_key_content) > 0:
                    previous_private_key = serialization.load_pem_private_key(
                        previous_private_key_content, password=None
                    )
        else:
            private_key_path = os.getenv("SECRETS_SERVICE_PRIVATE_KEY_PATH", "/secrets_service_private_key")
            private_key = serialization.load_pem_private_key(Path(private_key_path).read_bytes(), password=None)
            previous_secrets_service_private_key_path = os.getenv("PREVIOUS_SECRETS_SERVICE_PRIVATE_KEY_PATH")
            if previous_secrets_service_private_key_path and Path(previous_secrets_service_private_key_path).exists():
                previous_private_key = serialization.load_pem_private_key(
                    Path(previous_secrets_service_private_key_path).read_bytes(), password=None
                )
        if not isinstance(private_key, rsa.RSAPrivateKey):
            raise errors.ConfigurationError(message="Secret service private key is not an RSAPrivateKey")

        if previous_private_key is not None and not isinstance(previous_private_key, rsa.RSAPrivateKey):
            raise errors.ConfigurationError(message="Old secret service private key is not an RSAPrivateKey")

        return cls(private_key=private_key, previous_private_key=previous_private_key)


@dataclass
class Config:
    """Main config for secrets service."""

    db: DBConfig
    secrets: PrivateSecretsConfig
    keycloak: KeycloakConfig | None
    app_name: str = "secrets_storage"
    version: str = "0.0.1"
    dummy_stores: bool = False
    spec: dict[str, Any] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        spec_file = Path(renku_data_services.secrets.__file__).resolve().parent / "api.spec.yaml"
        with open(spec_file) as f:
            self.spec = safe_load(f)

    @classmethod
    def from_env(cls) -> Self:
        """Load values from environment."""
        dummy_stores = os.environ.get("DUMMY_STORES", "false").lower() == "true"
        db = DBConfig.from_env()
        secrets_config = PrivateSecretsConfig.from_env()
        version = os.environ.get("VERSION", "0.0.1")
        keycloak = None
        if not dummy_stores:
            KeycloakConfig.from_env()

        return cls(db=db, secrets=secrets_config, version=version, keycloak=keycloak)


@dataclass
class Wiring:
    """Wiring for secrets service."""

    authenticator: base_models.Authenticator
    config: Config
    core_client: K8sCoreClientInterface
    _user_secrets_repo: LowLevelUserSecretsRepo | None = field(default=None, repr=False, init=False)

    @property
    def user_secrets_repo(self) -> LowLevelUserSecretsRepo:
        """The DB adapter for users."""
        if not self._user_secrets_repo:
            self._user_secrets_repo = LowLevelUserSecretsRepo(
                session_maker=self.config.db.async_session_maker,
            )
        return self._user_secrets_repo

    @classmethod
    def from_env(cls) -> "Wiring":
        """Create a config from environment variables."""
        authenticator: base_models.Authenticator
        core_client: K8sCoreClientInterface
        config = Config.from_env()

        if config.dummy_stores:
            authenticator = DummyAuthenticator()
            core_client = DummyCoreClient({}, {})
        else:
            assert config.keycloak is not None
            oidc_disc_data = oidc_discovery(config.keycloak.keycloak_url, config.keycloak.keycloak_realm)
            jwks_url = oidc_disc_data.get("jwks_uri")
            if jwks_url is None:
                raise errors.ConfigurationError(
                    message="The JWKS url for Keycloak cannot be found from the OIDC discovery endpoint."
                )
            jwks = PyJWKClient(jwks_url)
            authenticator = KeycloakAuthenticator(jwks=jwks, algorithms=config.keycloak.algorithms)
            core_client = K8sCoreClient()

        return cls(
            config=config,
            authenticator=authenticator,
            core_client=core_client,
        )
