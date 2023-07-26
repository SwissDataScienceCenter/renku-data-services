"""Cloud storage app."""
from dataclasses import dataclass

import renku_data_services.base_models as base_models
from renku_data_services.base_api.auth import authenticate
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.base_api.error_handler import CustomErrorHandler
from renku_data_services.storage_adapters import StorageRepository
from renku_data_services.storage_schemas import apispec, query_parameters
from sanic import Request, Sanic, json

from renku_data_services.storage_api.config import Config


@dataclass(kw_only=True)
class StorageBP(CustomBlueprint):
    """Handlers for manipulating storage definitions."""

    storage_repo: StorageRepository
    authenticator: base_models.Authenticator

    def get(self) -> BlueprintFactoryResponse:
        """Get cloud storage for a repository."""

        @authenticate(self.authenticator)
        async def _get(request: Request, user: base_models.APIUser):
            res_filter = query_parameters.RepositoryFilter.parse_obj(dict(request.query_args))

            return json("")

        return "/storage", ["GET"], _get


def register_all_handlers(app: Sanic, config: Config) -> Sanic:
    """Register all handlers on the application."""
    url_prefix = "/api/storage"
    storage = StorageBP(
        name="storage",
        url_prefix=url_prefix,
        storage_repo=config.storage_repo,
        authenticator=config.authenticator,
    )

    app.blueprint(
        [
            storage.blueprint(),
        ]
    )

    app.error_handler = CustomErrorHandler(apispec)
    app.config.OAS = False
    app.config.OAS_UI_REDOC = False
    app.config.OAS_UI_SWAGGER = False
    app.config.OAS_AUTODOC = False
    return app
