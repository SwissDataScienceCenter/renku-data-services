"""Configurations."""
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from yaml import safe_load

from src import models
from src.db.adapter import DB
from src.users.dummy import DummyUserStore


@dataclass
class Config:
    """Configuration for the CRAC service."""

    db: DB
    spec_file: str = "src/api.spec.yaml"
    spec: Optional[Dict[str, Any]] = field(init=False, default=None)
    user_store: models.UserStore = DummyUserStore()
    version: str = "0.0.1"
    app_name: str = "renku_crac"

    def __post_init__(self):
        with open(self.spec_file, "r") as f:
            self.spec = safe_load(f)

    @classmethod
    def from_env(cls):
        """Create a config from environment variables."""

        prefix = ""
        async_sqlalchemy_url = os.environ.get(f"{prefix}SYNC_SQLALCHEMY_URL", "sqlite+aiosqlite:///data_services.db")
        sync_sqlalchemy_url = os.environ.get(f"{prefix}ASYNC_SQLALCHEMY_URL", "sqlite:///data_services.db")
        version = os.environ.get(f"{prefix}VERSION", "0.0.1")
        db = DB(sync_sqlalchemy_url, async_sqlalchemy_url)
        return cls(db, version=version)
