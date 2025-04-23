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

    @classmethod
    def from_env(cls, prefix: str = "") -> Config:
        """Creates a config object from environment variables."""

        dummy_stores = os.environ.get(f"{prefix}DUMMY_STORES", "false").lower() == "true"

        max_retry = int(os.environ.get(f"{prefix}MAX_RETRY_WAIT", "120"))
        main_tick = int(os.environ.get(f"{prefix}MAIN_TICK_INTERVAL", "300"))
        solr_config = SolrClientConfig.from_env(prefix)

        redis = RedisConfig.fake() if dummy_stores else RedisConfig.from_env(prefix)
        return Config(
            db_config=DBConfig.from_env(prefix),
            max_retry_wait=max_retry,
            main_tick_interval=main_tick,
            solr_config=solr_config,
            redis_config=redis,
        )
