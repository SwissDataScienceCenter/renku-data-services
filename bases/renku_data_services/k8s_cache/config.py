"""K8s cache config."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Self

from renku_data_services.db_config.config import DBConfig


@dataclass
class _K8sConfig:
    """Defines the k8s client and namespace."""

    # This is used only for the main/local/default cluster
    renku_namespace: str
    kube_config_root: str

    @classmethod
    def from_env(cls) -> Self:
        return cls(
            renku_namespace=os.environ.get("KUBERNETES_NAMESPACE", "default"),
            kube_config_root=os.environ.get("K8S_CONFIGS_ROOT", "/secrets/kube_configs"),
        )


@dataclass
class _MetricsConfig:
    """Configuration for metrics."""

    enabled: bool

    @classmethod
    def from_env(cls) -> _MetricsConfig:
        """Create metrics config from environment variables."""
        enabled = os.environ.get("POSTHOG_ENABLED", "false").lower() == "true"
        return cls(enabled)


@dataclass
class _ImageBuilderConfig:
    """Configuration for image builders."""

    enabled: bool

    @classmethod
    def from_env(cls) -> _ImageBuilderConfig:
        """Load values from environment variables."""
        enabled = os.environ.get("IMAGE_BUILDERS_ENABLED", "false").lower() == "true"
        return cls(enabled=enabled)


@dataclass
class _V1ServicesConfig:
    """Configuration for v1 services."""

    enabled: bool

    @classmethod
    def from_env(cls) -> _V1ServicesConfig:
        """Load values from environment variables."""
        enabled = os.environ.get("V1_SERVICES_ENABLED", "false").lower() == "true"
        return cls(enabled=enabled)


@dataclass
class Config:
    """K8s cache config."""

    db: DBConfig
    k8s: _K8sConfig
    metrics: _MetricsConfig
    image_builders: _ImageBuilderConfig
    v1_services: _V1ServicesConfig

    @classmethod
    def from_env(cls) -> Config:
        """Create a config from environment variables."""
        db = DBConfig.from_env()
        k8s = _K8sConfig.from_env()
        metrics = _MetricsConfig.from_env()
        image_builders = _ImageBuilderConfig.from_env()
        v1_services = _V1ServicesConfig.from_env()
        return cls(
            db=db,
            k8s=k8s,
            metrics=metrics,
            image_builders=image_builders,
            v1_services=v1_services,
        )
