"""Configurations."""
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict

from yaml import safe_load

import renku_data_services.base_models as base_models
import renku_data_services.storage_schemas
from renku_data_services import errors
from renku_data_services.storage_adapters import StorageRepository
from renku_data_services.users.dummy import DummyAuthenticator
from renku_data_services.users.gitlab import GitlabAuthenticator


@dataclass
class Config:
    """Configuration for the Cloud Storage service."""

    storage_repo: StorageRepository
    authenticator: base_models.Authenticator
    spec: Dict[str, Any] = field(init=False, default_factory=dict)
    version: str = "0.0.1"
    app_name: str = "renku_storage"

    def __post_init__(self):
        spec_file = Path(renku_data_services.storage_schemas.__file__).resolve().parent / "api.spec.yaml"
        with open(spec_file, "r") as f:
            self.spec = safe_load(f)

    @property
    def repo(self):
        """Used by alembic to find repo."""
        return self.storage_repo

    @classmethod
    def from_env(cls):
        """Create a config from environment variables."""

        prefix = ""
        authenticator: base_models.Authenticator
        version = os.environ.get(f"{prefix}VERSION", "0.0.1")

        if os.environ.get(f"{prefix}DUMMY_STORES", "false").lower() == "true":
            async_sqlalchemy_url = os.environ.get(
                f"{prefix}ASYNC_SQLALCHEMY_URL", "sqlite+aiosqlite:///storage_service.db"
            )
            sync_sqlalchemy_url = os.environ.get(f"{prefix}SYNC_SQLALCHEMY_URL", "sqlite:///storage_service.db")
            authenticator = DummyAuthenticator(admin=True)
        else:
            pg_host = os.environ.get("DB_HOST", "localhost")
            pg_user = os.environ.get("DB_USER", "renku")
            pg_port = os.environ.get("DB_PORT", "5432")
            db_name = os.environ.get("DB_NAME", "renku")
            pg_password = os.environ.get("DB_PASSWORD")
            if pg_password is None:
                raise errors.ConfigurationError(
                    message="Please provide a database password in the 'DB_PASSWORD' environment variable."
                )
            async_sqlalchemy_url = f"postgresql+asyncpg://{pg_user}:{pg_password}@{pg_host}:{pg_port}/{db_name}"
            sync_sqlalchemy_url = f"postgresql+psycopg2://{pg_user}:{pg_password}@{pg_host}:{pg_port}/{db_name}"
            gitlab_url = os.environ.get(f"{prefix}GITLAB_URL")
            if gitlab_url is None:
                raise errors.ConfigurationError(message="Please provide the gitlab instance URL")
            authenticator = GitlabAuthenticator(gitlab_url=gitlab_url)

        storage_repo = StorageRepository(
            sync_sqlalchemy_url=sync_sqlalchemy_url, async_sqlalchemy_url=async_sqlalchemy_url
        )
        return cls(
            storage_repo=storage_repo,
            version=version,
            authenticator=authenticator,
        )
