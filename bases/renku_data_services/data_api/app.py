"""Data service app."""

from collections.abc import Callable
from typing import Any

from sanic import Sanic
from sanic_ext.exceptions import ValidationError
from sanic_ext.extras.validation.validators import VALIDATION_ERROR
from ulid import ULID

from renku_data_services import errors
from renku_data_services.base_api.error_handler import CustomErrorHandler
from renku_data_services.base_api.misc import MiscBP
from renku_data_services.base_models.core import Slug
from renku_data_services.connected_services.blueprints import OAuth2ClientsBP, OAuth2ConnectionsBP
from renku_data_services.crc import apispec
from renku_data_services.crc.blueprints import (
    ClassesBP,
    ClustersBP,
    QuotaBP,
    ResourcePoolsBP,
    ResourcePoolUsersBP,
    UserResourcePoolsBP,
)
from renku_data_services.data_api.dependencies import DependencyManager
from renku_data_services.data_connectors.blueprints import DataConnectorsBP
from renku_data_services.namespace.blueprints import GroupsBP
from renku_data_services.notebooks.blueprints import NotebooksNewBP
from renku_data_services.notifications.blueprints import NotificationsBP
from renku_data_services.platform.blueprints import PlatformConfigBP, PlatformUrlRedirectBP
from renku_data_services.project.blueprints import ProjectsBP, ProjectSessionSecretBP
from renku_data_services.repositories.blueprints import RepositoriesBP
from renku_data_services.search.blueprints import SearchBP
from renku_data_services.search.reprovision import SearchReprovision
from renku_data_services.search.solr_user_query import UsernameResolve
from renku_data_services.session.blueprints import BuildsBP, EnvironmentsBP, SessionLaunchersBP
from renku_data_services.storage.blueprints import StorageBP, StorageSchemaBP
from renku_data_services.users.blueprints import KCUsersBP, UserPreferencesBP, UserSecretsBP


def str_to_slug(value: str) -> Slug:
    """Convert a str to Slug."""
    try:
        return Slug(value)
    except errors.ValidationError as err:
        raise ValueError("Couldn't parse slug") from err


def _patched_validate_body(
    validator: Callable[[type[Any], dict[str, Any]], Any],
    model: type[Any],
    body: dict[str, Any],
) -> Any:
    """Validate body method for monkey patching.

    sanic_ext does not return contained exceptions as errors anymore, instead it returns a string.
    This undoes that change.
    """
    try:
        return validator(model, body)
    except VALIDATION_ERROR as e:
        raise ValidationError(
            f"Invalid request body: {model.__name__}. Error: {e}",
            extra={"exception": e},
        ) from e


def register_all_handlers(app: Sanic, dm: DependencyManager) -> Sanic:
    """Register all handlers on the application."""
    # WARNING: The regex is not actually used in most cases, instead the conversion function must raise a ValueError
    app.router.register_pattern("ulid", ULID.from_str, r"^[0-7][0-9A-HJKMNP-TV-Z]{25}$")
    app.router.register_pattern("renku_slug", str_to_slug, r"^[a-zA-Z0-9][a-zA-Z0-9-_.]*$")

    url_prefix = "/api/data"
    resource_pools = ResourcePoolsBP(
        name="resource_pools",
        url_prefix=url_prefix,
        rp_repo=dm.rp_repo,
        authenticator=dm.authenticator,
        user_repo=dm.user_repo,
        cluster_repo=dm.cluster_repo,
    )
    classes = ClassesBP(name="classes", url_prefix=url_prefix, repo=dm.rp_repo, authenticator=dm.authenticator)
    quota = QuotaBP(
        name="quota",
        url_prefix=url_prefix,
        rp_repo=dm.rp_repo,
        authenticator=dm.authenticator,
    )
    users = KCUsersBP(name="users", url_prefix=url_prefix, repo=dm.kc_user_repo, authenticator=dm.authenticator)
    user_secrets = UserSecretsBP(
        name="user_secrets",
        url_prefix=url_prefix,
        secret_repo=dm.user_secrets_repo,
        authenticator=dm.authenticator,
    )
    resource_pools_users = ResourcePoolUsersBP(
        name="resource_pool_users",
        url_prefix=url_prefix,
        repo=dm.user_repo,
        authenticator=dm.authenticator,
        kc_user_repo=dm.kc_user_repo,
    )
    user_resource_pools = UserResourcePoolsBP(
        name="user_resource_pools",
        url_prefix=url_prefix,
        repo=dm.user_repo,
        authenticator=dm.authenticator,
        kc_user_repo=dm.kc_user_repo,
    )
    clusters = ClustersBP(name="clusters", url_prefix=url_prefix, repo=dm.cluster_repo, authenticator=dm.authenticator)
    storage = StorageBP(
        name="storage",
        url_prefix=url_prefix,
        storage_repo=dm.storage_repo,
        authenticator=dm.gitlab_authenticator,
    )
    storage_schema = StorageSchemaBP(name="storage_schema", url_prefix=url_prefix)
    user_preferences = UserPreferencesBP(
        name="user_preferences",
        url_prefix=url_prefix,
        user_preferences_repo=dm.user_preferences_repo,
        authenticator=dm.authenticator,
    )
    misc = MiscBP(name="misc", url_prefix=url_prefix, apispec=dm.spec, version=dm.config.version)
    project = ProjectsBP(
        name="projects",
        url_prefix=url_prefix,
        project_repo=dm.project_repo,
        project_member_repo=dm.project_member_repo,
        user_repo=dm.kc_user_repo,
        authenticator=dm.authenticator,
        data_connector_repo=dm.data_connector_repo,
        project_migration_repo=dm.project_migration_repo,
        session_repo=dm.session_repo,
        session_secret_repo=dm.project_session_secret_repo,
        metrics=dm.metrics,
    )
    project_session_secrets = ProjectSessionSecretBP(
        name="project_session_secrets",
        url_prefix=url_prefix,
        session_secret_repo=dm.project_session_secret_repo,
        authenticator=dm.authenticator,
    )
    group = GroupsBP(
        name="groups",
        url_prefix=url_prefix,
        authenticator=dm.authenticator,
        group_repo=dm.group_repo,
        metrics=dm.metrics,
    )
    session_environments = EnvironmentsBP(
        name="session_environments",
        url_prefix=url_prefix,
        session_repo=dm.session_repo,
        authenticator=dm.authenticator,
    )
    session_launchers = SessionLaunchersBP(
        name="sessions_launchers",
        url_prefix=url_prefix,
        session_repo=dm.session_repo,
        authenticator=dm.authenticator,
        metrics=dm.metrics,
    )
    builds = (
        BuildsBP(
            name="builds",
            url_prefix=url_prefix,
            session_repo=dm.session_repo,
            authenticator=dm.authenticator,
        )
        if dm.config.builds.enabled
        else None
    )
    oauth2_clients = OAuth2ClientsBP(
        name="oauth2_clients",
        url_prefix=url_prefix,
        connected_services_repo=dm.connected_services_repo,
        oauth_http_client_factory=dm.oauth_http_client_factory,
        authenticator=dm.authenticator,
    )
    oauth2_connections = OAuth2ConnectionsBP(
        name="oauth2_connections",
        url_prefix=url_prefix,
        connected_services_repo=dm.connected_services_repo,
        oauth_client_factory=dm.oauth_http_client_factory,
        authenticator=dm.authenticator,
        nb_config=dm.config.nb_config,
    )
    repositories = RepositoriesBP(
        name="repositories",
        url_prefix=url_prefix,
        git_repositories_repo=dm.git_repositories_repo,
        authenticator=dm.authenticator,
        internal_gitlab_authenticator=dm.gitlab_authenticator,
    )
    notebooks_new = NotebooksNewBP(
        name="notebooks",
        url_prefix=url_prefix,
        authenticator=dm.authenticator,
        nb_config=dm.config.nb_config,
        cluster_repo=dm.cluster_repo,
        data_connector_repo=dm.data_connector_repo,
        data_connector_secret_repo=dm.data_connector_secret_repo,
        git_provider_helper=dm.git_provider_helper,
        data_source_repo=dm.data_source_repo,
        image_check_repo=dm.image_check_repo,
        internal_gitlab_authenticator=dm.gitlab_authenticator,
        metrics=dm.metrics,
        oauth_client_factory=dm.oauth_http_client_factory,
        project_repo=dm.project_repo,
        project_session_secret_repo=dm.project_session_secret_repo,
        rp_repo=dm.rp_repo,
        session_repo=dm.session_repo,
        storage_repo=dm.storage_repo,
        user_repo=dm.kc_user_repo,
    )
    platform_config = PlatformConfigBP(
        name="platform_config",
        url_prefix=url_prefix,
        platform_repo=dm.platform_repo,
        authenticator=dm.authenticator,
    )
    platform_redirects = PlatformUrlRedirectBP(
        name="platform_redirects",
        url_prefix=url_prefix,
        url_redirect_repo=dm.url_redirect_repo,
        authenticator=dm.authenticator,
    )
    search = SearchBP(
        name="search2",
        url_prefix=url_prefix,
        authenticator=dm.authenticator,
        username_resolve=UsernameResolve.db(dm.kc_user_repo),
        search_reprovision=SearchReprovision(
            search_updates_repo=dm.search_updates_repo,
            reprovisioning_repo=dm.reprovisioning_repo,
            solr_config=dm.config.solr,
            user_repo=dm.kc_user_repo,
            group_repo=dm.group_repo,
            project_repo=dm.project_repo,
            data_connector_repo=dm.data_connector_repo,
        ),
        solr_config=dm.config.solr,
        authz=dm.authz,
        metrics=dm.metrics,
    )
    data_connectors = DataConnectorsBP(
        name="data_connectors",
        url_prefix=url_prefix,
        data_connector_repo=dm.data_connector_repo,
        data_connector_secret_repo=dm.data_connector_secret_repo,
        authenticator=dm.authenticator,
        metrics=dm.metrics,
    )
    notifications = NotificationsBP(
        name="notifications",
        url_prefix=url_prefix,
        notifications_repo=dm.notifications_repo,
        authenticator=dm.authenticator,
        alertmanager_webhook_role=dm.config.alertmanager_webhook_role,
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
            clusters.blueprint(),
            storage.blueprint(),
            storage_schema.blueprint(),
            user_preferences.blueprint(),
            misc.blueprint(),
            project.blueprint(),
            project_session_secrets.blueprint(),
            group.blueprint(),
            session_environments.blueprint(),
            session_launchers.blueprint(),
            oauth2_clients.blueprint(),
            oauth2_connections.blueprint(),
            repositories.blueprint(),
            notebooks_new.blueprint(),
            platform_config.blueprint(),
            search.blueprint(),
            data_connectors.blueprint(),
            platform_redirects.blueprint(),
            notifications.blueprint(),
        ]
    )
    if builds is not None:
        app.blueprint(builds.blueprint())

    # We need to patch sanic_ext as since version 24.12 they only send a string representation of errors
    import sanic_ext.extras.validation.setup

    sanic_ext.extras.validation.setup.validate_body = _patched_validate_body

    app.error_handler = CustomErrorHandler(apispec)
    app.config.OAS = False
    app.config.OAS_UI_REDOC = False
    app.config.OAS_UI_SWAGGER = False
    app.config.OAS_AUTODOC = False
    return app
