"""Configurations."""
import os
from dataclasses import dataclass, field
from typing import Any, Dict

from yaml import safe_load

import models
from db.adapter import ResourcePoolRepository, UserRepository
from users.dummy import DummyUserStore


@dataclass
class Config:
    """Configuration for the CRAC service."""

    user_repo: UserRepository
    rp_repo: ResourcePoolRepository
    spec_file: str = "src/api.spec.yaml"
    spec: Dict[str, Any] = field(init=False, default_factory=dict)
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
        async_sqlalchemy_url = os.environ.get(f"{prefix}ASYNC_SQLALCHEMY_URL", "sqlite+aiosqlite:///data_services.db")
        sync_sqlalchemy_url = os.environ.get(f"{prefix}SYNC_SQLALCHEMY_URL", "sqlite:///data_services.db")
        version = os.environ.get(f"{prefix}VERSION", "0.0.1")
        user_repo = UserRepository(sync_sqlalchemy_url=sync_sqlalchemy_url, async_sqlalchemy_url=async_sqlalchemy_url)
        rp_repo = ResourcePoolRepository(
            sync_sqlalchemy_url=sync_sqlalchemy_url, async_sqlalchemy_url=async_sqlalchemy_url
        )
        return cls(user_repo=user_repo, rp_repo=rp_repo, version=version)
