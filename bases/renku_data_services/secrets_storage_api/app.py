"""Secrets storage app."""

from sanic import Sanic

from renku_data_services.base_api.error_handler import CustomErrorHandler
from renku_data_services.base_api.misc import MiscBP
from renku_data_services.secrets import apispec
from renku_data_services.secrets.blueprints import K8sSecretsBP
from renku_data_services.secrets_storage_api.dependencies import DependencyManager


def register_all_handlers(app: Sanic, dm: DependencyManager) -> Sanic:
    """Register all handlers on the application."""
    url_prefix = "/api/secrets"
    secrets_storage = K8sSecretsBP(
        name="secrets_storage_api",
        url_prefix=url_prefix,
        user_secrets_repo=dm.user_secrets_repo,
        authenticator=dm.authenticator,
        secret_service_private_key=dm.config.secrets.private_key,
        previous_secret_service_private_key=dm.config.secrets.previous_private_key,
        client=dm.secret_client,
    )
    misc = MiscBP(name="misc", url_prefix=url_prefix, apispec=dm.config.spec, version=dm.config.version)
    app.blueprint([secrets_storage.blueprint(), misc.blueprint()])

    app.error_handler = CustomErrorHandler(apispec)
    app.config.OAS = False
    app.config.OAS_UI_REDOC = False
    app.config.OAS_UI_SWAGGER = False
    app.config.OAS_AUTODOC = False
    return app
