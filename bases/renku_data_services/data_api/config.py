"""Configuration for data api."""

import os
from dataclasses import dataclass
from typing import Self

from renku_data_services import errors
from renku_data_services.app_config.config import KeycloakConfig, PosthogConfig, SentryConfig, TrustedProxiesConfig
from renku_data_services.authz.config import AuthzConfig
from renku_data_services.db_config.config import DBConfig
from renku_data_services.message_queue.config import RedisConfig
from renku_data_services.notebooks.config import NotebooksConfig
from renku_data_services.notebooks.config.dynamic import ServerOptionsConfig
from renku_data_services.secrets.config import PublicSecretsConfig
from renku_data_services.session.config import BuildsConfig
from renku_data_services.solr.solr_client import SolrClientConfig
from renku_data_services.users.config import UserPreferencesConfig


@dataclass
class Config:
    """Application configuration."""

    dummy_stores: bool
    k8s_namespace: str
    db: DBConfig
    builds: BuildsConfig
    nb_config: NotebooksConfig
    secrets: PublicSecretsConfig
    sentry: SentryConfig
    posthog: PosthogConfig
    solr: SolrClientConfig
    authz_config: AuthzConfig
    trusted_proxies: TrustedProxiesConfig
    redis: RedisConfig
    keycloak: KeycloakConfig | None
    user_preferences: UserPreferencesConfig
    server_options: ServerOptionsConfig
    gitlab_url: str | None
    version: str = "0.0.1"

    @classmethod
    def from_env(cls, db: DBConfig | None = None) -> Self:
        """Load config from environment."""
        version = os.environ.get("VERSION", "0.0.1")
        dummy_stores = os.environ.get("DUMMY_STORES", "false").lower() == "true"
        k8s_namespace = os.environ.get("K8S_NAMESPACE", "default")
        builds = BuildsConfig.from_env()
        secrets = PublicSecretsConfig.from_env()
        if not db:
            db = DBConfig.from_env()
        sentry = SentryConfig.from_env()
        posthog = PosthogConfig.from_env()
        solr_config = SolrClientConfig.from_env()
        trusted_proxies = TrustedProxiesConfig.from_env()
        user_preferences_config = UserPreferencesConfig.from_env()
        nb_config = NotebooksConfig.from_env(db)
        server_options = ServerOptionsConfig.from_env()
        if dummy_stores:
            redis = RedisConfig.fake()
            keycloak = None
            gitlab_url = None
        else:
            redis = RedisConfig.from_env()
            keycloak = KeycloakConfig.from_env()
            gitlab_url = os.environ.get("GITLAB_URL")
            if gitlab_url is None:
                raise errors.ConfigurationError(message="Please provide the gitlab instance URL")
        authz_config = AuthzConfig.from_env()

        return cls(
            version=version,
            dummy_stores=dummy_stores,
            k8s_namespace=k8s_namespace,
            db=db,
            builds=builds,
            nb_config=nb_config,
            secrets=secrets,
            sentry=sentry,
            posthog=posthog,
            authz_config=authz_config,
            solr=solr_config,
            trusted_proxies=trusted_proxies,
            redis=redis,
            keycloak=keycloak,
            user_preferences=user_preferences_config,
            server_options=server_options,
            gitlab_url=gitlab_url,
        )
