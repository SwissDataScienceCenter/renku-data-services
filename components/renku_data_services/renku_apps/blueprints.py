"""Renku apps blueprints."""

from dataclasses import dataclass

from sanic import HTTPResponse, Request
from sanic.response import JSONResponse, json
from sanic_ext import validate
from ulid import ULID

from renku_data_services import base_models
from renku_data_services.base_api.auth import authenticate, only_authenticated
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.renku_apps import apispec
from renku_data_services.renku_apps.repository import RenkuAppsRepository


@dataclass(kw_only=True)
class RenkuAppBP(CustomBlueprint):
    """Handlers for Renku apps."""

    apps_repo: RenkuAppsRepository
    authenticator: base_models.Authenticator

    def post(self) -> BlueprintFactoryResponse:
        """Launch a new app from a session launcher."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate(json=apispec.AppPostRequest)
        async def _post(_: Request, user: base_models.APIUser, body: apispec.AppPostRequest) -> JSONResponse:
            app = await self.apps_repo.create_app(user=user, launcher_id=ULID.from_str(body.launcher_id))
            return json(app.as_apispec().model_dump(exclude_none=True, mode="json"), status=201)

        return "/apps", ["POST"], _post

    def get_one(self) -> BlueprintFactoryResponse:
        """Retrieve an app by name."""

        @authenticate(self.authenticator)
        async def _get_one(_: Request, user: base_models.APIUser, app_name: str) -> JSONResponse:
            app = await self.apps_repo.get_app(user=user, app_name=app_name)
            return json(app.as_apispec().model_dump(exclude_none=True, mode="json"))

        return "/apps/<app_name>", ["GET"], _get_one

    def delete_one(self) -> BlueprintFactoryResponse:
        """Delete an app by name."""

        @authenticate(self.authenticator)
        @only_authenticated
        async def _delete_one(_: Request, user: base_models.APIUser, app_name: str) -> HTTPResponse:
            await self.apps_repo.delete_app(user=user, app_name=app_name)
            return HTTPResponse(status=204)

        return "/apps/<app_name>", ["DELETE"], _delete_one
