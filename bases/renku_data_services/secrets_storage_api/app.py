"""Secrets storage app."""

from sanic import Sanic

from renku_data_services.base_api.error_handler import CustomErrorHandler
from renku_data_services.base_api.misc import MiscBP
from renku_data_services.secrets import apispec
from renku_data_services.secrets.blueprints import K8sSecretsBP
from renku_data_services.secrets.config import Config


def register_all_handlers(app: Sanic, config: Config) -> Sanic:
    """Register all handlers on the application."""
    url_prefix = "/api/secrets"
    secrets_storage = K8sSecretsBP(
        name="secrets_storage_api",
        url_prefix=url_prefix,
        user_secrets_repo=config.user_secrets_repo,
        authenticator=config.authenticator,
        secret_service_private_key=config.secrets_service_private_key,
        old_secret_service_private_key=config.old_secrets_service_private_key,
        core_client=config.core_client,
    )
    misc = MiscBP(name="misc", url_prefix=url_prefix, apispec=config.spec, version=config.version)
    app.blueprint([secrets_storage.blueprint(), misc.blueprint()])

    app.error_handler = CustomErrorHandler(apispec)
    app.config.OAS = False
    app.config.OAS_UI_REDOC = False
    app.config.OAS_UI_SWAGGER = False
    app.config.OAS_AUTODOC = False
    return app
