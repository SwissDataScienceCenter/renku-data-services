"""Dependencies management of secrets storage."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from renku_data_services import base_models
from renku_data_services.authn.dummy import DummyAuthenticator
from renku_data_services.authn.keycloak import KeycloakAuthenticator
from renku_data_services.crc.db import ClusterRepository
from renku_data_services.k8s.client_interfaces import SecretClient
from renku_data_services.k8s.clients import (
    DummyCoreClient,
    K8sClusterClientsPool,
    K8sSecretClient,
)
from renku_data_services.k8s.config import KubeConfigEnv, get_clusters
from renku_data_services.secrets.db import LowLevelUserSecretsRepo
from renku_data_services.secrets_storage_api.config import Config


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
            authenticator = KeycloakAuthenticator.new(config.keycloak)
            default_kubeconfig = KubeConfigEnv()

            secret_client = K8sSecretClient(
                K8sClusterClientsPool(
                    get_clusters(
                        kube_conf_root_dir=os.environ.get("K8S_CONFIGS_ROOT", "/secrets/kube_configs"),
                        default_kubeconfig=default_kubeconfig,
                        cluster_repo=cluster_repo,
                    )
                )
            )

        return cls(
            config=config,
            authenticator=authenticator,
            secret_client=secret_client,
        )
