"""Session Configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class SessionConfig:
    """Session configuration."""

    notebooks_url: str

    @classmethod
    def from_env(cls, prefix: str = ""):
        """Create a session configuration from environment variables."""
        notebooks_url = os.environ.get(f"{prefix}NOTEBOOKS_URL")
        return cls(notebooks_url=notebooks_url)
