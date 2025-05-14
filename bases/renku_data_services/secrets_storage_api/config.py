"""Secrets storage configuration."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Self

from yaml import safe_load

import renku_data_services.secrets
from renku_data_services.app_config.config import KeycloakConfig
from renku_data_services.db_config.config import DBConfig
from renku_data_services.secrets.config import PrivateSecretsConfig


@dataclass
class Config:
    """Main config for secrets service."""

    db: DBConfig
    secrets: PrivateSecretsConfig
    keycloak: KeycloakConfig | None
    app_name: str = "secrets_storage"
    version: str = "0.0.1"
    dummy_stores: bool = False
    spec: dict[str, Any] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        spec_file = Path(renku_data_services.secrets.__file__).resolve().parent / "api.spec.yaml"
        with open(spec_file) as f:
            self.spec = safe_load(f)

    @classmethod
    def from_env(cls) -> Self:
        """Load values from environment."""
        dummy_stores = os.environ.get("DUMMY_STORES", "false").lower() == "true"
        db = DBConfig.from_env()
        secrets_config = PrivateSecretsConfig.from_env()
        version = os.environ.get("VERSION", "0.0.1")
        keycloak = None
        if not dummy_stores:
            KeycloakConfig.from_env()

        return cls(db=db, secrets=secrets_config, version=version, keycloak=keycloak, dummy_stores=dummy_stores)
