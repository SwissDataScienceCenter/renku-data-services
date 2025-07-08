"""Dependencies management of secrets storage."""

from dataclasses import dataclass, field

from jwt import PyJWKClient

from renku_data_services import base_models, errors
from renku_data_services.authn.dummy import DummyAuthenticator
from renku_data_services.authn.keycloak import KeycloakAuthenticator
from renku_data_services.k8s.client_interfaces import SecretClient
from renku_data_services.k8s.clients import DummyCoreClient, K8sCoreClient
from renku_data_services.secrets.db import LowLevelUserSecretsRepo
from renku_data_services.secrets_storage_api.config import Config
from renku_data_services.utils.core import oidc_discovery


@dataclass
class DependencyManager:
    """Dependencies for secrets service."""

    authenticator: base_models.Authenticator
    config: Config
    core_client: SecretClient
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
    def from_env(cls) -> "DependencyManager":
        """Create a config from environment variables."""
        authenticator: base_models.Authenticator
        core_client: SecretClient
        config = Config.from_env()

        if config.dummy_stores:
            authenticator = DummyAuthenticator()
            core_client = DummyCoreClient({}, {})
        else:
            assert config.keycloak is not None
            oidc_disc_data = oidc_discovery(config.keycloak.url, config.keycloak.realm)
            jwks_url = oidc_disc_data.get("jwks_uri")
            if jwks_url is None:
                raise errors.ConfigurationError(
                    message="The JWKS url for Keycloak cannot be found from the OIDC discovery endpoint."
                )
            jwks = PyJWKClient(jwks_url)
            if config.keycloak.algorithms is None:
                raise errors.ConfigurationError(message="At least one token signature algorithm is required.")

            authenticator = KeycloakAuthenticator(jwks=jwks, algorithms=config.keycloak.algorithms)
            core_client = K8sCoreClient()

        return cls(
            config=config,
            authenticator=authenticator,
            core_client=core_client,
        )
