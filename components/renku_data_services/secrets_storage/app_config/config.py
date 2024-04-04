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
from dataclasses import dataclass, field
from pathlib import Path

from jwt import PyJWKClient

from renku_data_services import base_models, errors
from renku_data_services.app_config.config import oidc_discovery
from renku_data_services.authn.dummy import DummyAuthenticator
from renku_data_services.authn.keycloak import KeycloakAuthenticator
from renku_data_services.secrets_storage.db_config import SecretStorageDBConfig
from renku_data_services.secrets_storage.secret.db import SecretRepository


@dataclass
class Config:
    """Configuration for the Data service."""

    authenticator: base_models.Authenticator
    encryption_key: bytes = field(repr=False)
    db: SecretStorageDBConfig
    version: str = "0.1.0"
    app_name: str = "secrets_storage_api"
    _secret_repo: SecretRepository | None = field(default=None, repr=False, init=False)

    @property
    def secret_repo(self) -> SecretRepository:
        """The DB adapter for secrets."""
        if not self._secret_repo:
            self._secret_repo = SecretRepository(
                session_maker=self.db.async_session_maker,
                encryption_key=self.encryption_key,
            )
        return self._secret_repo

    @classmethod
    def from_env(cls, prefix: str = ""):
        """Create a config from environment variables."""
        authenticator: base_models.Authenticator
        db = SecretStorageDBConfig.from_env(prefix)

        encryption_key_path = os.getenv("ENCRYPTION_KEY_PATH", "/encryption-key")
        encryption_key = Path(encryption_key_path).read_bytes()

        if os.environ.get(f"{prefix}DUMMY_STORES", "false").lower() == "true":
            authenticator = DummyAuthenticator()
        else:

            if not encryption_key:
                raise errors.ConfigurationError(
                    message="The encryption key must be provided."
                )
            keycloak_url = os.environ.get(f"{prefix}KEYCLOAK_URL")
            if keycloak_url is None:
                raise errors.ConfigurationError(
                    message="The Keycloak URL has to be specified."
                )
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
                raise errors.ConfigurationError(
                    message="At least one token signature algorithm is required."
                )
            algorithms_lst = [i.strip() for i in algorithms.split(",")]
            jwks = PyJWKClient(jwks_url)
            authenticator = KeycloakAuthenticator(jwks=jwks, algorithms=algorithms_lst)

        return cls(authenticator=authenticator, db=db, encryption_key=encryption_key)
