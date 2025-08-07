"""Configuration for data api."""

import os
from dataclasses import dataclass
from typing import Self

from renku_data_services import errors
from renku_data_services.app_config.config import KeycloakConfig, PosthogConfig, SentryConfig, TrustedProxiesConfig
from renku_data_services.app_config.logging import Config as LoggingConfig
from renku_data_services.authz.config import AuthzConfig
from renku_data_services.db_config.config import DBConfig
from renku_data_services.notebooks.config import NotebooksConfig
from renku_data_services.notebooks.config.dynamic import ServerOptionsConfig
from renku_data_services.secrets.config import PublicSecretsConfig
from renku_data_services.session.config import BuildsConfig
from renku_data_services.solr.solr_client import SolrClientConfig
from renku_data_services.users.config import UserPreferencesConfig


@dataclass
class Config:
    """Application configuration."""

    enable_internal_gitlab: bool
    dummy_stores: bool
    k8s_namespace: str
    k8s_config_root: str
    db: DBConfig
    builds: BuildsConfig
    nb_config: NotebooksConfig
    secrets: PublicSecretsConfig
    sentry: SentryConfig
    posthog: PosthogConfig
    solr: SolrClientConfig
    authz_config: AuthzConfig
    trusted_proxies: TrustedProxiesConfig
    keycloak: KeycloakConfig | None
    user_preferences: UserPreferencesConfig
    server_options: ServerOptionsConfig
    gitlab_url: str | None
    log_cfg: LoggingConfig
    version: str

    @classmethod
    def from_env(cls, db: DBConfig | None = None) -> Self:
        """Load config from environment."""
        enable_internal_gitlab = os.getenv("ENABLE_V1_SERVICES", "true").lower() == "true"

        dummy_stores = os.environ.get("DUMMY_STORES", "false").lower() == "true"
        if db is None:
            db = DBConfig.from_env()

        if dummy_stores:
            keycloak = None
            gitlab_url = None
        else:
            keycloak = KeycloakConfig.from_env()
            if enable_internal_gitlab:
                gitlab_url = os.environ.get("GITLAB_URL")
                if gitlab_url is None:
                    raise errors.ConfigurationError(message="Please provide the gitlab instance URL")
            else:
                gitlab_url = None

        return cls(
            enable_internal_gitlab=enable_internal_gitlab,
            version=os.environ.get("VERSION", "0.0.1"),
            dummy_stores=dummy_stores,
            k8s_namespace=os.environ.get("K8S_NAMESPACE", "default"),
            k8s_config_root=os.environ.get("K8S_CONFIGS_ROOT", "/secrets/kube_configs"),
            db=db,
            builds=BuildsConfig.from_env(),
            nb_config=NotebooksConfig.from_env(db, enable_internal_gitlab=enable_internal_gitlab),
            secrets=PublicSecretsConfig.from_env(),
            sentry=SentryConfig.from_env(),
            posthog=PosthogConfig.from_env(),
            authz_config=AuthzConfig.from_env(),
            solr=SolrClientConfig.from_env(),
            trusted_proxies=TrustedProxiesConfig.from_env(),
            keycloak=keycloak,
            user_preferences=UserPreferencesConfig.from_env(),
            server_options=ServerOptionsConfig.from_env(),
            gitlab_url=gitlab_url,
            log_cfg=LoggingConfig.from_env(),
        )
