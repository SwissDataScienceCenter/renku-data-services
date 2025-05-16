"""Configurations for background jobs."""

from dataclasses import dataclass

from renku_data_services.app_config.config import KeycloakConfig
from renku_data_services.authz.config import AuthzConfig
from renku_data_services.db_config.config import DBConfig
from renku_data_services.message_queue.config import RedisConfig


@dataclass
class SyncConfig:
    """Main configuration."""

    authz: AuthzConfig
    redis: RedisConfig
    db: DBConfig
    keycloak: KeycloakConfig

    @classmethod
    def from_env(cls) -> "SyncConfig":
        """Generate a configuration from environment variables."""
        redis = RedisConfig.from_env()
        db = DBConfig.from_env()

        authz = AuthzConfig.from_env()
        keycloak = KeycloakConfig.from_env()
        return cls(authz=authz, redis=redis, db=db, keycloak=keycloak)
