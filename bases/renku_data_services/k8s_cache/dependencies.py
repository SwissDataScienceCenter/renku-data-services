"""Dependency management for k8s cache."""

from dataclasses import dataclass, field

from renku_data_services.crc.db import ClusterRepository, ResourcePoolRepository
from renku_data_services.k8s.clients import DummyCoreClient, DummySchedulingClient
from renku_data_services.k8s.quota import QuotaRepository
from renku_data_services.k8s_cache.config import Config
from renku_data_services.k8s_watcher.db import K8sDbCache
from renku_data_services.metrics.core import StagingMetricsService
from renku_data_services.metrics.db import MetricsRepository


@dataclass
class DependencyManager:
    """K8s cache config."""

    config: Config

    quota_repo: QuotaRepository
    _k8s_cache: K8sDbCache | None = None
    _metrics_repo: MetricsRepository | None = field(default=None, repr=False, init=False)
    _metrics: StagingMetricsService | None = field(default=None, repr=False, init=False)
    _rp_repo: ResourcePoolRepository | None = field(default=None, repr=False, init=False)
    _cluster_repo: ClusterRepository | None = field(default=None, repr=False, init=False)

    @property
    def metrics_repo(self) -> MetricsRepository:
        """The DB adapter for metrics."""
        if not self._metrics_repo:
            self._metrics_repo = MetricsRepository(session_maker=self.config.db.async_session_maker)
        return self._metrics_repo

    @property
    def metrics(self) -> StagingMetricsService:
        """The metrics service interface."""
        if not self._metrics:
            self._metrics = StagingMetricsService(enabled=self.config.metrics.enabled, metrics_repo=self.metrics_repo)
        return self._metrics

    @property
    def rp_repo(self) -> ResourcePoolRepository:
        """The resource pool repository."""
        if not self._rp_repo:
            self._rp_repo = ResourcePoolRepository(
                session_maker=self.config.db.async_session_maker, quotas_repo=self.quota_repo
            )
        return self._rp_repo

    def cluster_repo(self) -> ClusterRepository:
        """The resource pool repository."""
        if not self._cluster_repo:
            self._cluster_repo = ClusterRepository(session_maker=self.config.db.async_session_maker)
        return self._cluster_repo

    @property
    def k8s_cache(self) -> K8sDbCache:
        """The DB adapter for the k8s cache."""
        if not self._k8s_cache:
            self._k8s_cache = K8sDbCache(
                session_maker=self.config.db.async_session_maker,
            )
        return self._k8s_cache

    @classmethod
    def from_env(cls) -> "DependencyManager":
        """Create a config from environment variables."""
        config = Config.from_env()

        # NOTE: We only need the QuotaRepository to instantiate the ResourcePoolRepository which is used to get
        # the resource class and pool information for metrics. We don't need quota information for metrics at all
        # so we use the dummy client for quotas here as we don't actually access k8s, just the db.
        quota_repo = QuotaRepository(
            DummyCoreClient({}, {}), DummySchedulingClient({}), namespace=config.k8s.renku_namespace
        )

        return cls(
            config=config,
            quota_repo=quota_repo,
        )
