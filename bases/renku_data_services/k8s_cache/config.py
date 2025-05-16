"""K8s cache config."""

from dataclasses import dataclass, field
from typing import Self

from kubernetes.client.api_client import os

from renku_data_services.crc.db import ResourcePoolRepository
from renku_data_services.db_config.config import DBConfig
from renku_data_services.k8s.clients import DummyCoreClient, DummySchedulingClient
from renku_data_services.k8s.quota import QuotaRepository
from renku_data_services.k8s_watcher import K8sDbCache
from renku_data_services.metrics.core import StagingMetricsService
from renku_data_services.metrics.db import MetricsRepository


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
    def from_env(cls, prefix: str = "") -> "_MetricsConfig":
        """Create metrics config from environment variables."""
        enabled = os.environ.get(f"{prefix}POSTHOG_ENABLED", "false").lower() == "true"
        return cls(enabled)


@dataclass
class _ImageBuilderConfig:
    """Configuration for image builders."""

    enabled: bool

    @classmethod
    def from_env(cls, prefix: str = "") -> "_ImageBuilderConfig":
        """Load values from environment variables."""
        enabled = os.environ.get(f"{prefix}IMAGE_BUILDERS_ENABLED", "false").lower() == "true"
        return cls(enabled=enabled)


@dataclass
class Config:
    """K8s cache config."""

    db: DBConfig
    k8s: _K8sConfig
    metrics_config: _MetricsConfig
    image_builders: _ImageBuilderConfig
    quota_repo: QuotaRepository
    _k8s_cache: K8sDbCache | None = None
    _metrics_repo: MetricsRepository | None = field(default=None, repr=False, init=False)
    _metrics: StagingMetricsService | None = field(default=None, repr=False, init=False)
    _rp_repo: ResourcePoolRepository | None = field(default=None, repr=False, init=False)

    @property
    def metrics_repo(self) -> MetricsRepository:
        """The DB adapter for metrics."""
        if not self._metrics_repo:
            self._metrics_repo = MetricsRepository(session_maker=self.db.async_session_maker)
        return self._metrics_repo

    @property
    def metrics(self) -> StagingMetricsService:
        """The metrics service interface."""
        if not self._metrics:
            self._metrics = StagingMetricsService(enabled=self.metrics_config.enabled, metrics_repo=self.metrics_repo)
        return self._metrics

    @property
    def rp_repo(self) -> ResourcePoolRepository:
        """The resource pool repository."""
        if not self._rp_repo:
            self._rp_repo = ResourcePoolRepository(
                session_maker=self.db.async_session_maker, quotas_repo=self.quota_repo
            )
        return self._rp_repo

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
        db = DBConfig.from_env()
        k8s_config = _K8sConfig.from_env()
        metrics_config = _MetricsConfig.from_env(prefix)

        # NOTE: We only need the QuotaRepository to instantiate the ResourcePoolRepository which is used to get
        # the resource class and pool information for metrics. We don't need quota information for metrics at all
        # so we use the dummy client for quotas here as we don't actually access k8s, just the db.
        quota_repo = QuotaRepository(
            DummyCoreClient({}, {}), DummySchedulingClient({}), namespace=k8s_config.renku_namespace
        )
        image_builders = _ImageBuilderConfig.from_env(prefix)

        return cls(
            db=db,
            k8s=k8s_config,
            metrics_config=metrics_config,
            quota_repo=quota_repo,
            image_builders=image_builders,
        )
