"""Configuration for Renku apps."""

import os
from dataclasses import dataclass


@dataclass
class AppsConfig:
    """Configuration for Renku apps."""

    enabled: bool = False

    @classmethod
    def from_env(cls) -> "AppsConfig":
        """Create a config from environment variables."""
        enabled = os.environ.get("APPS_ENABLED", "false").lower() == "true"
        return cls(enabled=enabled)
