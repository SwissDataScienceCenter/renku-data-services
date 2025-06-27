"""Data tasks configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass

from renku_data_services.app_config.config import KeycloakConfig
from renku_data_services.authz.config import AuthzConfig
from renku_data_services.db_config.config import DBConfig
from renku_data_services.message_queue.config import RedisConfig
from renku_data_services.solr.solr_client import SolrClientConfig


@dataclass
class PosthogConfig:
    """Configuration for posthog."""

    enabled: bool
    api_key: str
    host: str
    environment: str

    @classmethod
    def from_env(
        cls,
    ) -> PosthogConfig:
        """Create posthog config from environment variables."""
        enabled = os.environ.get("POSTHOG_ENABLED", "false").lower() == "true"
        api_key = os.environ.get("POSTHOG_API_KEY", "")
        host = os.environ.get("POSTHOG_HOST", "")
        environment = os.environ.get("POSTHOG_ENVIRONMENT", "development")

        return cls(enabled, api_key, host, environment)


@dataclass
class Config:
    """Configuration for data tasks."""

    db: DBConfig
    solr: SolrClientConfig
    posthog: PosthogConfig
    redis: RedisConfig
    authz: AuthzConfig
    keycloak: KeycloakConfig | None
    dummy_stores: bool
    max_retry_wait_seconds: int
    main_log_interval_seconds: int
    tcp_host: str
    tcp_port: int
    short_task_period_s: int
    long_task_period_s: int

    @classmethod
    def from_env(cls) -> Config:
        """Creates a config object from environment variables."""

        dummy_stores = os.environ.get("DUMMY_STORES", "false").lower() == "true"

        max_retry = int(os.environ.get("MAX_RETRY_WAIT_SECONDS", "120"))
        main_tick = int(os.environ.get("MAIN_LOG_INTERVAL_SECONDS", "300"))
        solr_config = SolrClientConfig.from_env()
        posthog_config = PosthogConfig.from_env()
        tcp_host = os.environ.get("TCP_HOST", "127.0.0.1")
        tcp_port = int(os.environ.get("TCP_PORT", "8001"))

        short_task_period = int(os.environ.get("SHORT_TASK_PERIOD_S", 2 * 60))
        long_task_period = int(os.environ.get("LONG_TASK_PERIOD_S", 3 * 60 * 60))

        redis = RedisConfig.fake() if dummy_stores else RedisConfig.from_env()
        authz = AuthzConfig.from_env()

        keycloak = None if dummy_stores else KeycloakConfig.from_env()
        return Config(
            db=DBConfig.from_env(pool_size=4),
            max_retry_wait_seconds=max_retry,
            main_log_interval_seconds=main_tick,
            solr=solr_config,
            posthog=posthog_config,
            redis=redis,
            authz=authz,
            keycloak=keycloak,
            tcp_host=tcp_host,
            tcp_port=tcp_port,
            short_task_period_s=short_task_period,
            long_task_period_s=long_task_period,
            dummy_stores=dummy_stores,
        )
