"""K8s cache config."""

from dataclasses import dataclass
from typing import Self

from kubernetes.client.api_client import os

from renku_data_services.db_config.config import DBConfig


@dataclass
class _K8sConfig:
    """Defines the k8s client and namespace."""

    renku_namespace: str = "default"

    @classmethod
    def from_env(cls) -> Self:
        return cls(renku_namespace=os.environ.get("KUBERNETES_NAMESPACE", "default"))


@dataclass
class _MetricsConfig:
    """Configuration for metrics."""

    enabled: bool

    @classmethod
    def from_env(cls) -> "_MetricsConfig":
        """Create metrics config from environment variables."""
        enabled = os.environ.get("POSTHOG_ENABLED", "false").lower() == "true"
        return cls(enabled)


@dataclass
class _ImageBuilderConfig:
    """Configuration for image builders."""

    enabled: bool

    @classmethod
    def from_env(cls) -> "_ImageBuilderConfig":
        """Load values from environment variables."""
        enabled = os.environ.get("IMAGE_BUILDERS_ENABLED", "false").lower() == "true"
        return cls(enabled=enabled)


@dataclass
class Config:
    """K8s cache config."""

    db: DBConfig
    k8s: _K8sConfig
    metrics: _MetricsConfig
    image_builders: _ImageBuilderConfig

    @classmethod
    def from_env(cls) -> "Config":
        """Create a config from environment variables."""
        db = DBConfig.from_env(pool_size=4)
        k8s = _K8sConfig.from_env()
        metrics = _MetricsConfig.from_env()

        image_builders = _ImageBuilderConfig.from_env()

        return cls(
            db=db,
            k8s=k8s,
            metrics=metrics,
            image_builders=image_builders,
        )
