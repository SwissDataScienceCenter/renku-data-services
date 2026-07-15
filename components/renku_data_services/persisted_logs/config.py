"""Configuration for persisted logs."""

from dataclasses import dataclass


@dataclass(eq=True, frozen=True, kw_only=True)
class PersistedLogsConfig:
    """Configuration for persisted logs."""

    enabled: bool
    loki_read_base_url: str
    namespace: str

    @classmethod
    def from_env(cls, namespace: str) -> "PersistedLogsConfig":
        """Create a config from environment variables."""
        # enabled = os.environ.get("PERSISTED_LOG_ENABLED", "false").lower() == "true"
        # return cls(
        #     enabled=enabled,
        # )

        return cls(
            enabled=True,
            loki_read_base_url="http://loki-read.monitoring.svc.cluster.local:3100/",
            namespace=namespace,
        )
