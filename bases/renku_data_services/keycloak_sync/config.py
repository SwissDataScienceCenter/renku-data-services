"""Configurations for Keycloak syncing."""
import os
from dataclasses import dataclass, field

from renku_data_services.errors import errors
from renku_data_services.keycloak_sync.db import DB
from renku_data_services.users.kc_api import KeycloakAPI


@dataclass
class SyncConfig:
    """Main configuration."""

    async_sqlalchemy_url: str = field(repr=False)
    sync_sqlalchemy_url: str = field(repr=False)
    db: DB
    kc_api: KeycloakAPI
    total_user_sync: bool = False

    @classmethod
    def from_env(cls):
        """Generate a configuration from environment variables."""
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
        sync_sqlalchemy_url = f"postgresql+psycopg://{pg_user}:{pg_password}@{pg_host}:{pg_port}/{db_name}"
        db = DB(sync_sqlalchemy_url, async_sqlalchemy_url)
        keycloak_url = os.environ["KEYCLOAK_URL"]
        client_id = os.environ["KEYCLOAK_CLIENT_ID"]
        client_secret = os.environ["KEYCLOAK_CLIENT_SECRET"]
        realm = os.environ.get("KEYCLOAK_REALM", "Renku")
        kc_api = KeycloakAPI(keycloak_url=keycloak_url, client_id=client_id, client_secret=client_secret, realm=realm)
        total_user_sync = os.environ.get("TOTAL_USER_SYNC", "false").lower() == "true"
        return cls(async_sqlalchemy_url, sync_sqlalchemy_url, db, kc_api, total_user_sync)
