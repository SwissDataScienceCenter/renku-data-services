"""Configuration for the metering endpoint."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class OpenMeterConfig:
    """Configuration for the OpenMeter metering endpoint."""

    enabled: bool
    endpoint_url: str
    token: str

    @classmethod
    def from_env(cls) -> OpenMeterConfig:
        """Create OpenMeter config from environment variables."""
        return cls(
            enabled=os.environ.get("OPENMETER_ENABLED", "false").lower() == "true",
            endpoint_url=os.environ.get("OPENMETER_ENDPOINT_URL", ""),
            token=os.environ.get("OPENMETER_API_TOKEN", ""),
        )
