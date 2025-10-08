"""Configurations.

An important thing to note here is that the configuration classes in here
contain some getters (i.e. @property decorators) intentionally. This is done for
things that need a database connection and the purpose is that the database connection
is not initialized when the classes are initialized. Only if the properties that need
the database will instantiate a connection when they are used. And even in this case
a single connection will be reused. This allows for the configuration classes to be
instantiated multiple times without creating multiple database connections.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from renku_data_services import errors


@dataclass
class KeycloakConfig:
    """Configuration values for keycloak."""

    url: str
    realm: str
    client_id: str
    client_secret: str
    algorithms: list[str] | None

    @classmethod
    def from_env(cls) -> KeycloakConfig:
        """Load config from environment values."""
        url = os.environ.get("KEYCLOAK_URL")
        if url is None:
            raise errors.ConfigurationError(message="The Keycloak URL has to be specified.")
        url = url.rstrip("/")
        realm = os.environ.get("KEYCLOAK_REALM", "Renku")
        client_id = os.environ["KEYCLOAK_CLIENT_ID"]
        client_secret = os.environ["KEYCLOAK_CLIENT_SECRET"]
        algorithms = os.environ.get("KEYCLOAK_TOKEN_SIGNATURE_ALGS")
        algorithms_lst = None
        if algorithms is not None:
            algorithms_lst = [i.strip() for i in algorithms.split(",")]
        return cls(
            url=url,
            realm=realm,
            client_id=client_id,
            client_secret=client_secret,
            algorithms=algorithms_lst,
        )


@dataclass
class SentryConfig:
    """Configuration for sentry."""

    enabled: bool
    dsn: str
    environment: str
    release: str
    sample_rate: float = 0.2

    @classmethod
    def from_env(cls) -> SentryConfig:
        """Create a config from environment variables."""
        enabled = os.environ.get("SENTRY_ENABLED", "false").lower() == "true"
        dsn = os.environ.get("SENTRY_DSN", "")
        environment = os.environ.get("SENTRY_ENVIRONMENT", "")
        release = os.environ.get("VERSION", "")
        sample_rate = float(os.environ.get("SENTRY_SAMPLE_RATE", "0.2"))

        return cls(enabled, dsn=dsn, environment=environment, release=release, sample_rate=sample_rate)


@dataclass
class PosthogConfig:
    """Configuration for posthog."""

    enabled: bool

    @classmethod
    def from_env(cls) -> PosthogConfig:
        """Create posthog config from environment variables."""
        enabled = os.environ.get("POSTHOG_ENABLED", "false").lower() == "true"

        return cls(enabled)


@dataclass
class TrustedProxiesConfig:
    """Configuration for trusted reverse proxies."""

    proxies_count: int | None = None
    real_ip_header: str | None = None

    @classmethod
    def from_env(cls) -> TrustedProxiesConfig:
        """Create a config from environment variables."""
        proxies_count = int(os.environ.get("PROXIES_COUNT") or "0")
        real_ip_header = os.environ.get("REAL_IP_HEADER")
        return cls(proxies_count=proxies_count or None, real_ip_header=real_ip_header or None)
