"""Data service app."""

from collections.abc import Callable
from typing import Any

from sanic import Sanic
from sanic_ext.exceptions import ValidationError
from sanic_ext.extras.validation.validators import VALIDATION_ERROR
from ulid import ULID

from renku_data_services import errors
from renku_data_services.app_config import Wiring
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
from renku_data_services.data_connectors.blueprints import DataConnectorsBP
from renku_data_services.message_queue.blueprints import MessageQueueBP
from renku_data_services.namespace.blueprints import GroupsBP
from renku_data_services.notebooks.blueprints import NotebooksBP, NotebooksNewBP
from renku_data_services.platform.blueprints import PlatformConfigBP
from renku_data_services.project.blueprints import ProjectsBP, ProjectSessionSecretBP
from renku_data_services.repositories.blueprints import RepositoriesBP
from renku_data_services.search.blueprints import SearchBP
from renku_data_services.search.reprovision import SearchReprovision
from renku_data_services.session.blueprints import BuildsBP, EnvironmentsBP, SessionLaunchersBP
from renku_data_services.storage.blueprints import StorageBP, StorageSchemaBP
from renku_data_services.users.blueprints import KCUsersBP, UserPreferencesBP, UserSecretsBP


def str_to_slug(value: str) -> Slug:
    """Convert a str to Slug."""
    try:
        return Slug(value)
    except errors.ValidationError:
        raise ValueError("Couldn't parse slug")


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


def register_all_handlers(app: Sanic, wiring: Wiring) -> Sanic:
    """Register all handlers on the application."""
    # WARNING: The regex is not actually used in most cases, instead the conversion function must raise a ValueError
    app.router.register_pattern("ulid", ULID.from_str, r"^[0-7][0-9A-HJKMNP-TV-Z]{25}$")
    app.router.register_pattern("renku_slug", str_to_slug, r"^[a-zA-Z0-9][a-zA-Z0-9-_.]*$")

    url_prefix = "/api/data"
    resource_pools = ResourcePoolsBP(
        name="resource_pools",
        url_prefix=url_prefix,
        rp_repo=wiring.rp_repo,
        authenticator=wiring.authenticator,
        user_repo=wiring.user_repo,
    )
    classes = ClassesBP(name="classes", url_prefix=url_prefix, repo=wiring.rp_repo, authenticator=wiring.authenticator)
    quota = QuotaBP(
        name="quota",
        url_prefix=url_prefix,
        rp_repo=wiring.rp_repo,
        authenticator=wiring.authenticator,
        quota_repo=wiring.quota_repo,
    )
    users = KCUsersBP(name="users", url_prefix=url_prefix, repo=wiring.kc_user_repo, authenticator=wiring.authenticator)
    user_secrets = UserSecretsBP(
        name="user_secrets",
        url_prefix=url_prefix,
        secret_repo=wiring.user_secrets_repo,
        authenticator=wiring.authenticator,
    )
    resource_pools_users = ResourcePoolUsersBP(
        name="resource_pool_users",
        url_prefix=url_prefix,
        repo=wiring.user_repo,
        authenticator=wiring.authenticator,
        kc_user_repo=wiring.kc_user_repo,
    )
    user_resource_pools = UserResourcePoolsBP(
        name="user_resource_pools",
        url_prefix=url_prefix,
        repo=wiring.user_repo,
        authenticator=wiring.authenticator,
        kc_user_repo=wiring.kc_user_repo,
    )
    clusters = ClustersBP(
        name="clusters", url_prefix=url_prefix, repo=wiring.cluster_repo, authenticator=wiring.authenticator
    )
    storage = StorageBP(
        name="storage",
        url_prefix=url_prefix,
        storage_repo=wiring.storage_repo,
        authenticator=wiring.gitlab_authenticator,
    )
    storage_schema = StorageSchemaBP(name="storage_schema", url_prefix=url_prefix)
    user_preferences = UserPreferencesBP(
        name="user_preferences",
        url_prefix=url_prefix,
        user_preferences_repo=wiring.user_preferences_repo,
        authenticator=wiring.authenticator,
    )
    misc = MiscBP(name="misc", url_prefix=url_prefix, apispec=wiring.spec, version=wiring.version)
    project = ProjectsBP(
        name="projects",
        url_prefix=url_prefix,
        project_repo=wiring.project_repo,
        project_member_repo=wiring.project_member_repo,
        authenticator=wiring.authenticator,
        user_repo=wiring.kc_user_repo,
        session_repo=wiring.session_repo,
        data_connector_repo=wiring.data_connector_repo,
        project_migration_repo=wiring.project_migration_repo,
        metrics=wiring.metrics,
    )
    project_session_secrets = ProjectSessionSecretBP(
        name="project_session_secrets",
        url_prefix=url_prefix,
        session_secret_repo=wiring.project_session_secret_repo,
        authenticator=wiring.authenticator,
    )
    group = GroupsBP(
        name="groups",
        url_prefix=url_prefix,
        authenticator=wiring.authenticator,
        group_repo=wiring.group_repo,
        metrics=wiring.metrics,
    )
    session_environments = EnvironmentsBP(
        name="session_environments",
        url_prefix=url_prefix,
        session_repo=wiring.session_repo,
        authenticator=wiring.authenticator,
    )
    session_launchers = SessionLaunchersBP(
        name="sessions_launchers",
        url_prefix=url_prefix,
        session_repo=wiring.session_repo,
        authenticator=wiring.authenticator,
        metrics=wiring.metrics,
    )
    builds = (
        BuildsBP(
            name="builds",
            url_prefix=url_prefix,
            session_repo=wiring.session_repo,
            authenticator=wiring.authenticator,
        )
        if wiring.config.builds.enabled
        else None
    )
    oauth2_clients = OAuth2ClientsBP(
        name="oauth2_clients",
        url_prefix=url_prefix,
        connected_services_repo=wiring.connected_services_repo,
        authenticator=wiring.authenticator,
    )
    oauth2_connections = OAuth2ConnectionsBP(
        name="oauth2_connections",
        url_prefix=url_prefix,
        connected_services_repo=wiring.connected_services_repo,
        authenticator=wiring.authenticator,
        internal_gitlab_authenticator=wiring.gitlab_authenticator,
    )
    repositories = RepositoriesBP(
        name="repositories",
        url_prefix=url_prefix,
        git_repositories_repo=wiring.git_repositories_repo,
        authenticator=wiring.authenticator,
        internal_gitlab_authenticator=wiring.gitlab_authenticator,
    )
    notebooks = NotebooksBP(
        name="notebooks_old",
        url_prefix=url_prefix,
        authenticator=wiring.authenticator,
        nb_config=wiring.nb_config,
        internal_gitlab_authenticator=wiring.gitlab_authenticator,
        git_repo=wiring.git_repositories_repo,
        rp_repo=wiring.rp_repo,
        user_repo=wiring.kc_user_repo,
        storage_repo=wiring.storage_repo,
    )
    notebooks_new = NotebooksNewBP(
        name="notebooks",
        url_prefix=url_prefix,
        authenticator=wiring.authenticator,
        nb_config=wiring.nb_config,
        project_repo=wiring.project_repo,
        project_session_secret_repo=wiring.project_session_secret_repo,
        session_repo=wiring.session_repo,
        storage_repo=wiring.storage_repo,
        rp_repo=wiring.rp_repo,
        user_repo=wiring.kc_user_repo,
        data_connector_repo=wiring.data_connector_repo,
        data_connector_secret_repo=wiring.data_connector_secret_repo,
        internal_gitlab_authenticator=wiring.gitlab_authenticator,
        metrics=wiring.metrics,
    )
    platform_config = PlatformConfigBP(
        name="platform_config",
        url_prefix=url_prefix,
        platform_repo=wiring.platform_repo,
        authenticator=wiring.authenticator,
    )
    message_queue = MessageQueueBP(
        name="search",
        url_prefix=url_prefix,
        authenticator=wiring.authenticator,
        session_maker=wiring.config.db.async_session_maker,
        reprovisioning_repo=wiring.reprovisioning_repo,
        user_repo=wiring.kc_user_repo,
        group_repo=wiring.group_repo,
        project_repo=wiring.project_repo,
        authz=wiring.authz,
    )
    search = SearchBP(
        name="search2",
        url_prefix=url_prefix,
        authenticator=wiring.authenticator,
        search_reprovision=SearchReprovision(
            search_updates_repo=wiring.search_updates_repo,
            reprovisioning_repo=wiring.reprovisioning_repo,
            solr_config=wiring.config.solr,
            user_repo=wiring.kc_user_repo,
            group_repo=wiring.group_repo,
            project_repo=wiring.project_repo,
            data_connector_repo=wiring.data_connector_repo,
        ),
        solr_config=wiring.config.solr,
        authz=wiring.authz,
        metrics=wiring.metrics,
    )
    data_connectors = DataConnectorsBP(
        name="data_connectors",
        url_prefix=url_prefix,
        data_connector_repo=wiring.data_connector_repo,
        data_connector_secret_repo=wiring.data_connector_secret_repo,
        authenticator=wiring.authenticator,
        metrics=wiring.metrics,
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
            notebooks.blueprint(),
            notebooks_new.blueprint(),
            platform_config.blueprint(),
            message_queue.blueprint(),
            search.blueprint(),
            data_connectors.blueprint(),
        ]
    )
    if builds is not None:
        app.blueprint(builds.blueprint())

    # We need to patch sanic_extz as since version 24.12 they only send a string representation of errors
    import sanic_ext.extras.validation.setup

    sanic_ext.extras.validation.setup.validate_body = _patched_validate_body

    app.error_handler = CustomErrorHandler(apispec)
    app.config.OAS = False
    app.config.OAS_UI_REDOC = False
    app.config.OAS_UI_SWAGGER = False
    app.config.OAS_AUTODOC = False
    return app
