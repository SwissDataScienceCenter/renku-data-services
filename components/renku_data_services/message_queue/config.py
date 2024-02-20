"""Configuration for message queue client."""

import os
from dataclasses import dataclass, field
from typing import Any, Dict

import redis


@dataclass
class RedisConfig:
    """Message queue configuration."""

    password: str = field(repr=False)
    is_sentinel: bool = False
    host: str = "renku-redis"
    port: int = 6379
    datatbase: int = 0
    sentinel_master_set: str = "mymaster"

    _connection: redis.Redis | None = None

    @classmethod
    def from_env(cls, prefix: str = ""):
        """Create a config from environment variables."""
        is_sentinel = os.environ.get(f"{prefix}REDIS_IS_SENTINEL")
        host = os.environ.get(f"{prefix}REDIS_HOST")
        port = os.environ.get(f"{prefix}REDIS_PORT")
        database = os.environ.get(f"{prefix}REDIS_DATABASE")
        sentinel_master_set = os.environ.get(f"{prefix}REDIS_MASTER_SET")
        password = os.environ.get(f"{prefix}REDIS_PASSWORD")
        kwargs: Dict[str, Any] = {}
        if is_sentinel is not None:
            kwargs["is_sentinel"] = bool(is_sentinel)
        if host is not None:
            kwargs["host"] = host
        if port is not None:
            kwargs["port"] = int(port)
        if database is not None:
            kwargs["database"] = int(database)
        if sentinel_master_set is not None:
            kwargs["sentinel_master_set"] = sentinel_master_set
        if password is not None:
            kwargs["password"] = password

        return cls(**kwargs)

    @classmethod
    def fake(cls):
        """Create a config using fake redis."""
        import fakeredis

        instance = cls(password="")
        instance._connection = fakeredis.FakeRedis()
        return instance

    def redis_connection(self) -> redis.Redis:
        """Get a redis connection."""
        if self._connection is None:
            if self.is_sentinel:
                sentinel = redis.Sentinel([(self.host, self.port)], sentinel_kwargs={"password": self.password})
                self._connection = sentinel.master_for(
                    self.sentinel_master_set,
                    db=self.datatbase,
                    password=self.password,
                    retry_on_timeout=True,
                    health_check_interval=60,
                )
            else:
                self._connection = redis.Redis(
                    host=self.host,
                    port=self.port,
                    db=self.datatbase,
                    password=self.password,
                    retry_on_timeout=True,
                    health_check_interval=60,
                )
        return self._connection
