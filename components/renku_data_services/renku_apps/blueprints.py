"""Renku apps blueprints."""

from dataclasses import dataclass

from sanic import HTTPResponse, Request
from sanic.response import JSONResponse
from sanic_ext import validate

from renku_data_services.base_api.auth import (
    authenticate,
)

from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.renku_apps import apispec

@dataclass(kw_only=True)
class RenkuAppBP:
    """Handlers for renku apps."""

    def post(self) -> BlueprintFactoryResponse:
        """Create a new renku app."""

        @authenticate(self.authenticator)
        @validate(json=apispec.AppPostRequest)
        async def _post(_: Request, user: base_models.APIUser, body: apispec.AppPostRequest) -> JSONResponse:

        return "/apps", ["POST"], _post
