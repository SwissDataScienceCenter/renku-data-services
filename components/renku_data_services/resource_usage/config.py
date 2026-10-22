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
    meter_key: str
    feature_key: str
    customer_key_prefix: str

    @classmethod
    def from_env(cls) -> OpenMeterConfig:
        """Create OpenMeter config from environment variables."""
        return cls(
            enabled=os.environ.get("OPENMETER_ENABLED", "false").lower() == "true",
            endpoint_url=os.environ.get("OPENMETER_ENDPOINT_URL", ""),
            token=os.environ.get("OPENMETER_API_TOKEN", ""),
            meter_key=os.environ.get("OPENMETER_METER_KEY", "compute_units"),
            feature_key=os.environ.get("OPENMETER_FEATURE_KEY", "compute_units"),
            customer_key_prefix=os.environ.get("OPENMETER_CUSTOMER_KEY_PREFIX", "renku-pool-"),
        )
