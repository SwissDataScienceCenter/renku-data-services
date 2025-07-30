"""Dependencies management of secrets storage."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from jwt import PyJWKClient

from renku_data_services import base_models, errors
from renku_data_services.authn.dummy import DummyAuthenticator
from renku_data_services.authn.keycloak import KeycloakAuthenticator
from renku_data_services.crc.db import ClusterRepository
from renku_data_services.k8s.client_interfaces import SecretClient
from renku_data_services.k8s.clients import DummyCoreClient, K8sClusterClientsPool, K8sSecretClient
from renku_data_services.k8s.config import KubeConfigEnv, get_clusters
from renku_data_services.k8s.db import K8sDbCache
from renku_data_services.notebooks.constants import AMALTHEA_SESSION_GVK, JUPYTER_SESSION_GVK
from renku_data_services.secrets.db import LowLevelUserSecretsRepo
from renku_data_services.secrets_storage_api.config import Config
from renku_data_services.session.constants import BUILD_RUN_GVK, TASK_RUN_GVK
from renku_data_services.utils.core import oidc_discovery


@dataclass
class DependencyManager:
    """Dependencies for secrets service."""

    authenticator: base_models.Authenticator
    config: Config
    secret_client: SecretClient
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
    def from_env(cls) -> DependencyManager:
        """Create a config from environment variables."""
        authenticator: base_models.Authenticator
        secret_client: SecretClient
        config = Config.from_env()
        cluster_repo = ClusterRepository(session_maker=config.db.async_session_maker)

        if config.dummy_stores:
            authenticator = DummyAuthenticator()
            secret_client = DummyCoreClient({}, {})
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
            api = KubeConfigEnv().api()
            secret_client = K8sSecretClient(
                K8sClusterClientsPool(
                    cache=K8sDbCache(config.db.async_session_maker),
                    kinds_to_cache=[AMALTHEA_SESSION_GVK, JUPYTER_SESSION_GVK, BUILD_RUN_GVK, TASK_RUN_GVK],
                    clusters=get_clusters(
                        kube_conf_root_dir=os.environ.get("K8S_CONFIGS_ROOT", "/secrets/kube_configs"),
                        namespace=api.namespace,
                        api=api,
                        cluster_rp=cluster_repo,
                    ),
                )
            )

        return cls(
            config=config,
            authenticator=authenticator,
            secret_client=secret_client,
        )
