"""K8s cache config."""

from dataclasses import dataclass
from typing import Self

from kubernetes.client.api_client import os

from renku_data_services.db_config.config import DBConfig
from renku_data_services.k8s_watcher.db import K8sDbCache


@dataclass
class _K8sConfig:
    """Defines the k8s client and namespace."""

    renku_namespace: str = "default"

    @classmethod
    def from_env(cls) -> Self:
        return cls(renku_namespace=os.environ.get("KUBERNETES_NAMESPACE", "default"))


@dataclass
class Config:
    """K8s cache config."""

    db: DBConfig
    k8s: _K8sConfig

    @property
    def k8s_cache(self) -> K8sDbCache:
        """The DB adapter for the k8s cache."""
        if not self._k8s_cache:
            self._k8s_cache = K8sDbCache(
                session_maker=self.db.async_session_maker,
            )
        return self._k8s_cache

    @classmethod
    def from_env(cls, prefix: str = "") -> "Config":
        """Create a config from environment variables."""
        db = DBConfig.from_env(prefix)
        k8s_config = _K8sConfig.from_env()

        return cls(db=db, k8s=k8s_config)
