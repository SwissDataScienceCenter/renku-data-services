"""Data service app."""
from sanic import Sanic

from renku_data_services.base_api.error_handler import CustomErrorHandler
from renku_data_services.base_api.misc import MiscBP
from renku_data_services.crc.blueprints import (
    ClassesBP,
    QuotaBP,
    ResourcePoolsBP,
    ResourcePoolUsersBP,
    UserResourcePoolsBP,
    UsersBP,
)
from renku_data_services.crc import apispec
from renku_data_services.data_api.config import Config
from renku_data_services.storage_blueprints import StorageBP, StorageSchemaBP


def register_all_handlers(app: Sanic, config: Config) -> Sanic:
    """Register all handlers on the application."""
    url_prefix = "/api/data"
    resource_pools = ResourcePoolsBP(
        name="resource_pools",
        url_prefix=url_prefix,
        rp_repo=config.rp_repo,
        authenticator=config.authenticator,
        user_repo=config.user_repo,
        quota_repo=config.quota_repo,
    )
    classes = ClassesBP(name="classes", url_prefix=url_prefix, repo=config.rp_repo, authenticator=config.authenticator)
    quota = QuotaBP(
        name="quota",
        url_prefix=url_prefix,
        rp_repo=config.rp_repo,
        authenticator=config.authenticator,
        quota_repo=config.quota_repo,
    )
    resource_pools_users = ResourcePoolUsersBP(
        name="resource_pool_users", url_prefix=url_prefix, repo=config.user_repo, authenticator=config.authenticator
    )
    users = UsersBP(
        name="users",
        url_prefix=url_prefix,
        repo=config.user_repo,
        user_store=config.user_store,
        authenticator=config.authenticator,
    )
    user_resource_pools = UserResourcePoolsBP(
        name="user_resource_pools",
        url_prefix=url_prefix,
        repo=config.user_repo,
        authenticator=config.authenticator,
        quota_repo=config.quota_repo,
    )
    storage = StorageBP(
        name="storage",
        url_prefix=url_prefix,
        storage_repo=config.storage_repo,
        authenticator=config.gitlab_authenticator,
    )
    storage_schema = StorageSchemaBP(name="storage_schema", url_prefix=url_prefix)
    misc = MiscBP(name="misc", url_prefix=url_prefix, apispec=config.spec, version=config.version)
    app.blueprint(
        [
            resource_pools.blueprint(),
            classes.blueprint(),
            quota.blueprint(),
            resource_pools_users.blueprint(),
            users.blueprint(),
            user_resource_pools.blueprint(),
            storage.blueprint(),
            storage_schema.blueprint(),
            misc.blueprint(),
        ]
    )

    app.error_handler = CustomErrorHandler(apispec)
    app.config.OAS = False
    app.config.OAS_UI_REDOC = False
    app.config.OAS_UI_SWAGGER = False
    app.config.OAS_AUTODOC = False
    return app
