"""Configuration for message queue client."""

import os
import random
from dataclasses import dataclass, field

import redis.asyncio as redis


@dataclass
class RedisConfig:
    """Message queue configuration."""

    password: str = field(repr=False)
    is_sentinel: bool = False
    host: str = "renku-redis"
    port: int = 6379
    database: int = 0
    sentinel_master_set: str = "mymaster"

    _connection: redis.Redis | None = None

    @classmethod
    def from_env(cls) -> "RedisConfig":
        """Create a config from environment variables."""
        is_sentinel = os.environ.get("REDIS_IS_SENTINEL", "false")
        host = os.environ.get("REDIS_HOST", "localhost")
        port = os.environ.get("REDIS_PORT", 6379)
        database = os.environ.get("REDIS_DATABASE", 0)
        sentinel_master_set = os.environ.get("REDIS_MASTER_SET", "mymaster")
        password = os.environ.get("REDIS_PASSWORD", "")

        return cls(
            host=host,
            port=int(port),
            database=int(database),
            password=password,
            sentinel_master_set=sentinel_master_set,
            is_sentinel=is_sentinel.lower() == "true",
        )

    @classmethod
    def fake(cls) -> "RedisConfig":
        """Create a config using fake redis."""
        import fakeredis

        instance = cls(password="")  # nosec B106
        # by default, fake redis shares instances across instantiations. We want a new instance per test,
        # so we change the port.
        instance._connection = fakeredis.FakeAsyncRedis(port=random.randint(1000, 65535))  # nosec: B311
        return instance

    @property
    def redis_connection(self) -> redis.Redis:
        """Get a redis connection."""
        if self._connection is None:
            if self.is_sentinel:
                sentinel = redis.Sentinel([(self.host, self.port)], sentinel_kwargs={"password": self.password})
                self._connection = sentinel.master_for(
                    self.sentinel_master_set,
                    db=self.database,
                    password=self.password,
                    retry_on_timeout=True,
                    health_check_interval=60,
                )
            else:
                self._connection = redis.Redis(
                    host=self.host,
                    port=self.port,
                    db=self.database,
                    password=self.password,
                    retry_on_timeout=True,
                    health_check_interval=60,
                )
        return self._connection

    def reset_redis_connection(self) -> None:
        """Forces a full reconnect to redis."""
        self._connection = None
