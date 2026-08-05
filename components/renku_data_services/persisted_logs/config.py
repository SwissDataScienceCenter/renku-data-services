"""Configuration for persisted logs."""

import os
from dataclasses import dataclass
from datetime import timedelta


@dataclass(eq=True, frozen=True, kw_only=True)
class PersistedLogsConfig:
    """Configuration for persisted logs."""

    enabled: bool
    loki_read_base_url: str
    namespace: str
    logs_ttl: timedelta

    @classmethod
    def from_env(cls, namespace: str) -> "PersistedLogsConfig":
        """Create a config from environment variables."""
        enabled = os.environ.get("PERSISTED_LOG_ENABLED", "false").lower() == "true"
        logs_ttl_seconds = int(os.environ.get("PERSISTED_LOGS_TTL_SECONDS", "86400"))
        return cls(
            enabled=enabled,
            loki_read_base_url=os.environ.get("PERSISTED_LOGS_LOKI_READ_URL", ""),
            namespace=namespace,
            logs_ttl=timedelta(seconds=logs_ttl_seconds),
        )
