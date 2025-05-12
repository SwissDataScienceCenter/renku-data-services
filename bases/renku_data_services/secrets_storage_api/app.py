"""Secrets storage app."""

from sanic import Sanic

from renku_data_services.base_api.error_handler import CustomErrorHandler
from renku_data_services.base_api.misc import MiscBP
from renku_data_services.secrets import apispec
from renku_data_services.secrets.blueprints import K8sSecretsBP
from renku_data_services.secrets.config import Wiring


def register_all_handlers(app: Sanic, wiring: Wiring) -> Sanic:
    """Register all handlers on the application."""
    url_prefix = "/api/secrets"
    secrets_storage = K8sSecretsBP(
        name="secrets_storage_api",
        url_prefix=url_prefix,
        user_secrets_repo=wiring.user_secrets_repo,
        authenticator=wiring.authenticator,
        secret_service_private_key=wiring.config.secrets.private_key,
        previous_secret_service_private_key=wiring.config.secrets.previous_private_key,
        core_client=wiring.core_client,
    )
    misc = MiscBP(name="misc", url_prefix=url_prefix, apispec=wiring.config.spec, version=wiring.config.version)
    app.blueprint([secrets_storage.blueprint(), misc.blueprint()])

    app.error_handler = CustomErrorHandler(apispec)
    app.config.OAS = False
    app.config.OAS_UI_REDOC = False
    app.config.OAS_UI_SWAGGER = False
    app.config.OAS_AUTODOC = False
    return app
