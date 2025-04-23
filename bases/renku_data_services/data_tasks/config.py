"""Data tasks configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass

from renku_data_services.db_config.config import DBConfig
from renku_data_services.message_queue.config import RedisConfig
from renku_data_services.solr.solr_client import SolrClientConfig


@dataclass
class Config:
    """Configuration for data tasks."""

    db_config: DBConfig
    solr_config: SolrClientConfig
    redis_config: RedisConfig
    max_retry_wait: int
    main_tick_interval: int
    tcp_host: str
    tcp_port: int

    @classmethod
    def from_env(cls, prefix: str = "") -> Config:
        """Creates a config object from environment variables."""

        def env(key: str, default: str) -> str:
            return os.environ.get(f"{prefix}{key}", default)

        dummy_stores = env("DUMMY_STORES", "false").lower() == "true"

        max_retry = int(env("MAX_RETRY_WAIT", "120"))
        main_tick = int(env("MAIN_TICK_INTERVAL", "300"))
        solr_config = SolrClientConfig.from_env(prefix)
        tcp_host = env("TCP_HOST", "127.0.0.1")
        tcp_port = int(env("TCP_PORT", "8001"))

        redis = RedisConfig.fake() if dummy_stores else RedisConfig.from_env(prefix)
        return Config(
            db_config=DBConfig.from_env(prefix),
            max_retry_wait=max_retry,
            main_tick_interval=main_tick,
            solr_config=solr_config,
            redis_config=redis,
            tcp_host=tcp_host,
            tcp_port=tcp_port,
        )
