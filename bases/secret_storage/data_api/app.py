"""Secret storage app."""

from sanic import Sanic
from secret_storage.app_config import Config
from secret_storage.secret import apispec
from secret_storage.secret.blueprints import SecretsBP

from renku_data_services.base_api.error_handler import CustomErrorHandler


def register_all_handlers(app: Sanic, config: Config) -> Sanic:
    """Register all handlers on the application."""
    url_prefix = "/api/secret"
    secret_storage = SecretsBP(
        name="secret_storage",
        url_prefix=url_prefix,
        secret_repo=config.secret_repo,
        authenticator=config.authenticator,
    )
    app.blueprint([secret_storage.blueprint()])

    app.error_handler = CustomErrorHandler(apispec)
    app.config.OAS = False
    app.config.OAS_UI_REDOC = False
    app.config.OAS_UI_SWAGGER = False
    app.config.OAS_AUTODOC = False
    return app
