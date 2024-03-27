"""Secrets storage app."""

from sanic import Sanic

from renku_data_services.base_api.error_handler import CustomErrorHandler
from renku_data_services.secrets_storage.app_config import Config
from renku_data_services.secrets_storage.secret import apispec
from renku_data_services.secrets_storage.secret.blueprints import SecretsBP


def register_all_handlers(app: Sanic, config: Config) -> Sanic:
    """Register all handlers on the application."""
    url_prefix = "/api/secret"
    secrets_storage = SecretsBP(
        name="secrets_storage_api",
        url_prefix=url_prefix,
        secret_repo=config.secret_repo,
        authenticator=config.authenticator,
    )
    app.blueprint([secrets_storage.blueprint()])

    app.error_handler = CustomErrorHandler(apispec)
    app.config.OAS = False
    app.config.OAS_UI_REDOC = False
    app.config.OAS_UI_SWAGGER = False
    app.config.OAS_AUTODOC = False
    return app
