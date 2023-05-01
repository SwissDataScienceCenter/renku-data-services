"""Configurations."""
import os
from dataclasses import dataclass, field
from typing import Any, Dict

from yaml import safe_load

from src import models
from src.db.adapter import ResourcePoolRepository, UserRepository
from src.users.dummy import DummyUserStore


@dataclass
class Config:
    """Configuration for the CRAC service."""

    user_repo: UserRepository
    rp_repo: ResourcePoolRepository
    spec_file: str = "src/api.spec.yaml"
    spec: Dict[str, Any] = field(init=False, default_factory=dict)
    user_store: models.UserStore = DummyUserStore()
    version: str = "0.0.1"

    def __post_init__(self):
        with open(self.spec_file, "r") as f:
            self.spec = safe_load(f)

    @classmethod
    def from_env(cls):
        """Create a config from environment variables."""

        prefix = ""
        sql_url_default = "sqlite+aiosqlite:///data_services.db"
        sql_url = os.environ.get(f"{prefix}SQLALCHEMY_URL")
        if not sql_url:
            sql_url = sql_url_default
        version = os.environ.get(f"{prefix}VERSION", "0.0.1")
        user_repo = UserRepository(sql_url)
        rp_repo = ResourcePoolRepository(sql_url)
        return cls(user_repo=user_repo, rp_repo=rp_repo, version=version)
