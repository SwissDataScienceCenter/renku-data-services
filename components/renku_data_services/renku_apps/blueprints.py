"""Renku apps blueprints."""

from dataclasses import dataclass
from typing import Any

from sanic import HTTPResponse, Request
from sanic.response import JSONResponse
from sanic_ext import validate
from ulid import ULID

from renku_data_services import base_models
from renku_data_services.base_api.auth import authenticate, only_authenticated
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.base_models.validation import validated_json
from renku_data_services.renku_apps import apispec
from renku_data_services.renku_apps.models import App
from renku_data_services.renku_apps.repository import RenkuAppsRepository


@dataclass(kw_only=True)
class RenkuAppBP(CustomBlueprint):
    """Handlers for Renku apps."""

    apps_repo: RenkuAppsRepository
    authenticator: base_models.Authenticator

    @staticmethod
    def _dump_app(app: App) -> dict[str, Any]:
        """Dump an app for API responses."""
        return dict(
            name=app.name,
            launcher_id=str(app.launcher_id),
            project_id=str(app.project_id),
            status=app.status.value,
            url=app.url,
            started=app.started.isoformat() if app.started is not None else None,
            image=app.image,
        )

    def post(self) -> BlueprintFactoryResponse:
        """Launch a new app from a session launcher."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate(json=apispec.AppPostRequest)
        async def _post(_: Request, user: base_models.APIUser, body: apispec.AppPostRequest) -> JSONResponse:
            app = await self.apps_repo.create_app(user=user, launcher_id=ULID.from_str(body.launcher_id))
            return validated_json(apispec.AppResponse, self._dump_app(app), status=201)

        return "/apps", ["POST"], _post

    def get_one(self) -> BlueprintFactoryResponse:
        """Retrieve an app by name."""

        @authenticate(self.authenticator)
        async def _get_one(_: Request, user: base_models.APIUser, app_name: str) -> JSONResponse:
            app = await self.apps_repo.get_app(user=user, app_name=app_name)
            return validated_json(apispec.AppResponse, self._dump_app(app))

        return "/apps/<app_name>", ["GET"], _get_one

    def delete_one(self) -> BlueprintFactoryResponse:
        """Delete an app by name."""

        @authenticate(self.authenticator)
        @only_authenticated
        async def _delete_one(_: Request, user: base_models.APIUser, app_name: str) -> HTTPResponse:
            await self.apps_repo.delete_app(user=user, app_name=app_name)
            return HTTPResponse(status=204)

        return "/apps/<app_name>", ["DELETE"], _delete_one

    def patch_one(self) -> BlueprintFactoryResponse:
        """Patch an app."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate(json=apispec.AppPatchRequest)
        async def _patch_one(
            _: Request, user: base_models.APIUser, body: apispec.AppPatchRequest, app_name: str
        ) -> JSONResponse:
            app = await self.apps_repo.update_app(
                user=user,
                app_name=app_name,
                state=body.state,
            )
            return validated_json(apispec.AppResponse, self._dump_app(app))

        return "/apps/<app_name>", ["PATCH"], _patch_one

    def get_all(self) -> BlueprintFactoryResponse:
        """Get all apps, optionally filtered by project ID."""

        @authenticate(self.authenticator)
        @validate(query=apispec.AppsGetParametersQuery)
        async def _get_all(
            _: Request, user: base_models.APIUser, query: apispec.AppsGetParametersQuery
        ) -> JSONResponse:
            project_id = ULID.from_str(query.project_id) if query.project_id is not None else None
            apps = await self.apps_repo.list_apps(user=user, project_id=project_id)
            return validated_json(apispec.AppListResponse, [self._dump_app(app) for app in apps])

        return "/apps", ["GET"], _get_all
