"""Data tasks configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass

from renku_data_services.db_config.config import DBConfig


@dataclass
class Config:
    """Configuration for data tasks."""

    db_config: DBConfig
    max_retry_wait: int

    @classmethod
    def from_env(cls, prefix: str = "") -> Config:
        """Creates a config object from environment variables."""
        max_retry = int(os.environ.get(f"{prefix}MAX_RETRY_WAIT", "120"))
        return Config(db_config=DBConfig.from_env(prefix), max_retry_wait=max_retry)
