"""Data service app."""

from sanic import Sanic
from ulid import ULID

from renku_data_services.app_config import Config
from renku_data_services.base_api.error_handler import CustomErrorHandler
from renku_data_services.base_api.misc import MiscBP
from renku_data_services.connected_services.blueprints import OAuth2ClientsBP, OAuth2ConnectionsBP
from renku_data_services.crc import apispec
from renku_data_services.crc.blueprints import (
    ClassesBP,
    QuotaBP,
    ResourcePoolsBP,
    ResourcePoolUsersBP,
    UserResourcePoolsBP,
)
from renku_data_services.namespace.blueprints import GroupsBP
from renku_data_services.platform.blueprints import PlatformConfigBP
from renku_data_services.project.blueprints import ProjectsBP
from renku_data_services.repositories.blueprints import RepositoriesBP
from renku_data_services.session.blueprints import EnvironmentsBP, SessionLaunchersBP
from renku_data_services.storage.blueprints import StorageBP, StorageSchemaBP, StoragesV2BP
from renku_data_services.users.blueprints import KCUsersBP, UserPreferencesBP, UserSecretsBP


def register_all_handlers(app: Sanic, config: Config) -> Sanic:
    """Register all handlers on the application."""
    app.router.register_pattern("ulid", ULID.from_str, r"^[0-7][0-9A-HJKMNP-TV-Z]{25}$")
    app.router.register_pattern("renku_slug", str, r"^[a-zA-Z0-9][a-zA-Z0-9\-_.]*$")

    url_prefix = "/api/data"
    resource_pools = ResourcePoolsBP(
        name="resource_pools",
        url_prefix=url_prefix,
        rp_repo=config.rp_repo,
        authenticator=config.authenticator,
        user_repo=config.user_repo,
    )
    classes = ClassesBP(name="classes", url_prefix=url_prefix, repo=config.rp_repo, authenticator=config.authenticator)
    quota = QuotaBP(
        name="quota",
        url_prefix=url_prefix,
        rp_repo=config.rp_repo,
        authenticator=config.authenticator,
        quota_repo=config.quota_repo,
    )
    users = KCUsersBP(name="users", url_prefix=url_prefix, repo=config.kc_user_repo, authenticator=config.authenticator)
    user_secrets = UserSecretsBP(
        name="user_secrets",
        url_prefix=url_prefix,
        user_repo=config.kc_user_repo,
        secret_repo=config.user_secrets_repo,
        secret_service_public_key=config.secrets_service_public_key,
        authenticator=config.authenticator,
    )
    resource_pools_users = ResourcePoolUsersBP(
        name="resource_pool_users",
        url_prefix=url_prefix,
        repo=config.user_repo,
        authenticator=config.authenticator,
        kc_user_repo=config.kc_user_repo,
    )
    user_resource_pools = UserResourcePoolsBP(
        name="user_resource_pools",
        url_prefix=url_prefix,
        repo=config.user_repo,
        authenticator=config.authenticator,
        kc_user_repo=config.kc_user_repo,
    )
    storage = StorageBP(
        name="storage",
        url_prefix=url_prefix,
        storage_repo=config.storage_repo,
        authenticator=config.gitlab_authenticator,
    )
    storages_v2 = StoragesV2BP(
        name="storages_v2",
        url_prefix=url_prefix,
        storage_v2_repo=config.storage_v2_repo,
        authenticator=config.authenticator,
    )
    storage_schema = StorageSchemaBP(name="storage_schema", url_prefix=url_prefix)
    user_preferences = UserPreferencesBP(
        name="user_preferences",
        url_prefix=url_prefix,
        user_preferences_repo=config.user_preferences_repo,
        authenticator=config.authenticator,
    )
    misc = MiscBP(name="misc", url_prefix=url_prefix, apispec=config.spec, version=config.version)
    project = ProjectsBP(
        name="projects",
        url_prefix=url_prefix,
        project_repo=config.project_repo,
        project_member_repo=config.project_member_repo,
        authenticator=config.authenticator,
        user_repo=config.kc_user_repo,
    )
    group = GroupsBP(
        name="groups",
        url_prefix=url_prefix,
        authenticator=config.authenticator,
        group_repo=config.group_repo,
    )
    session_environments = EnvironmentsBP(
        name="session_environments",
        url_prefix=url_prefix,
        session_repo=config.session_repo,
        authenticator=config.authenticator,
    )
    session_launchers = SessionLaunchersBP(
        name="sessions_launchers",
        url_prefix=url_prefix,
        session_repo=config.session_repo,
        authenticator=config.authenticator,
    )
    oauth2_clients = OAuth2ClientsBP(
        name="oauth2_clients",
        url_prefix=url_prefix,
        connected_services_repo=config.connected_services_repo,
        authenticator=config.authenticator,
    )
    oauth2_connections = OAuth2ConnectionsBP(
        name="oauth2_connections",
        url_prefix=url_prefix,
        connected_services_repo=config.connected_services_repo,
        authenticator=config.authenticator,
        internal_gitlab_authenticator=config.gitlab_authenticator,
    )
    repositories = RepositoriesBP(
        name="repositories",
        url_prefix=url_prefix,
        git_repositories_repo=config.git_repositories_repo,
        authenticator=config.authenticator,
        internal_gitlab_authenticator=config.gitlab_authenticator,
    )
    platform_config = PlatformConfigBP(
        name="platform_config",
        url_prefix=url_prefix,
        platform_repo=config.platform_repo,
        authenticator=config.authenticator,
    )
    app.blueprint(
        [
            resource_pools.blueprint(),
            classes.blueprint(),
            quota.blueprint(),
            resource_pools_users.blueprint(),
            users.blueprint(),
            user_secrets.blueprint(),
            user_resource_pools.blueprint(),
            storage.blueprint(),
            storages_v2.blueprint(),
            storage_schema.blueprint(),
            user_preferences.blueprint(),
            misc.blueprint(),
            project.blueprint(),
            group.blueprint(),
            session_environments.blueprint(),
            session_launchers.blueprint(),
            oauth2_clients.blueprint(),
            oauth2_connections.blueprint(),
            repositories.blueprint(),
            platform_config.blueprint(),
        ]
    )

    app.error_handler = CustomErrorHandler(apispec)
    app.config.OAS = False
    app.config.OAS_UI_REDOC = False
    app.config.OAS_UI_SWAGGER = False
    app.config.OAS_AUTODOC = False
    return app
