"""Session blueprint."""

from dataclasses import dataclass

from sanic import HTTPResponse, Request, json
from sanic.response import JSONResponse
from sanic_ext import validate
from ulid import ULID

import renku_data_services.base_models as base_models
from renku_data_services.base_api.auth import authenticate
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.session import apispec
from renku_data_services.session.db import SessionRepository


@dataclass(kw_only=True)
class EnvironmentsBP(CustomBlueprint):
    """Handlers for manipulating session environments."""

    session_repo: SessionRepository
    authenticator: base_models.Authenticator

    def get_all(self) -> BlueprintFactoryResponse:
        """List all session environments."""

        async def _get_all(_: Request) -> JSONResponse:
            environments = await self.session_repo.get_environments()
            return json(
                [apispec.Environment.model_validate(e).model_dump(exclude_none=True, mode="json") for e in environments]
            )

        return "/environments", ["GET"], _get_all

    def get_one(self) -> BlueprintFactoryResponse:
        """Get a specific session environment."""

        async def _get_one(_: Request, environment_id: ULID) -> JSONResponse:
            environment = await self.session_repo.get_environment(environment_id=environment_id)
            return json(apispec.Environment.model_validate(environment).model_dump(exclude_none=True, mode="json"))

        return "/environments/<environment_id:ulid>", ["GET"], _get_one

    def post(self) -> BlueprintFactoryResponse:
        """Create a new session environment."""

        @authenticate(self.authenticator)
        @validate(json=apispec.EnvironmentPost)
        async def _post(_: Request, user: base_models.APIUser, body: apispec.EnvironmentPost) -> JSONResponse:
            environment = await self.session_repo.insert_environment(user=user, new_environment=body)
            return json(apispec.Environment.model_validate(environment).model_dump(exclude_none=True, mode="json"), 201)

        return "/environments", ["POST"], _post

    def patch(self) -> BlueprintFactoryResponse:
        """Partially update a specific session environment."""

        @authenticate(self.authenticator)
        @validate(json=apispec.EnvironmentPatch)
        async def _patch(
            _: Request, user: base_models.APIUser, environment_id: ULID, body: apispec.EnvironmentPatch
        ) -> JSONResponse:
            body_dict = body.model_dump(exclude_none=True)
            environment = await self.session_repo.update_environment(
                user=user, environment_id=environment_id, **body_dict
            )
            return json(apispec.Environment.model_validate(environment).model_dump(exclude_none=True, mode="json"))

        return "/environments/<environment_id:ulid>", ["PATCH"], _patch

    def delete(self) -> BlueprintFactoryResponse:
        """Delete a specific session environment."""

        @authenticate(self.authenticator)
        async def _delete(_: Request, user: base_models.APIUser, environment_id: ULID) -> HTTPResponse:
            await self.session_repo.delete_environment(user=user, environment_id=environment_id)
            return HTTPResponse(status=204)

        return "/environments/<environment_id:ulid>", ["DELETE"], _delete


@dataclass(kw_only=True)
class SessionLaunchersBP(CustomBlueprint):
    """Handlers for manipulating session launcher."""

    session_repo: SessionRepository
    authenticator: base_models.Authenticator

    def get_all(self) -> BlueprintFactoryResponse:
        """List all session launcher visible to user."""

        @authenticate(self.authenticator)
        async def _get_all(_: Request, user: base_models.APIUser) -> JSONResponse:
            launchers = await self.session_repo.get_launchers(user=user)
            return json(
                [
                    apispec.SessionLauncher.model_validate(item).model_dump(exclude_none=True, mode="json")
                    for item in launchers
                ]
            )

        return "/session_launchers", ["GET"], _get_all

    def get_one(self) -> BlueprintFactoryResponse:
        """Get a specific session launcher."""

        @authenticate(self.authenticator)
        async def _get_one(_: Request, user: base_models.APIUser, launcher_id: ULID) -> JSONResponse:
            launcher = await self.session_repo.get_launcher(user=user, launcher_id=launcher_id)
            return json(apispec.SessionLauncher.model_validate(launcher).model_dump(exclude_none=True, mode="json"))

        return "/session_launchers/<launcher_id:ulid>", ["GET"], _get_one

    def post(self) -> BlueprintFactoryResponse:
        """Create a new session launcher."""

        @authenticate(self.authenticator)
        @validate(json=apispec.SessionLauncherPost)
        async def _post(_: Request, user: base_models.APIUser, body: apispec.SessionLauncherPost) -> JSONResponse:
            launcher = await self.session_repo.insert_launcher(user=user, new_launcher=body)
            return json(
                apispec.SessionLauncher.model_validate(launcher).model_dump(exclude_none=True, mode="json"), 201
            )

        return "/session_launchers", ["POST"], _post

    def patch(self) -> BlueprintFactoryResponse:
        """Partially update a specific session launcher."""

        @authenticate(self.authenticator)
        @validate(json=apispec.SessionLauncherPatch)
        async def _patch(
            _: Request, user: base_models.APIUser, launcher_id: ULID, body: apispec.SessionLauncherPatch
        ) -> JSONResponse:
            body_dict = body.model_dump(exclude_none=True)
            launcher = await self.session_repo.update_launcher(user=user, launcher_id=launcher_id, **body_dict)
            return json(apispec.SessionLauncher.model_validate(launcher).model_dump(exclude_none=True, mode="json"))

        return "/session_launchers/<launcher_id:ulid>", ["PATCH"], _patch

    def delete(self) -> BlueprintFactoryResponse:
        """Delete a specific session launcher."""

        @authenticate(self.authenticator)
        async def _delete(_: Request, user: base_models.APIUser, launcher_id: ULID) -> HTTPResponse:
            await self.session_repo.delete_launcher(user=user, launcher_id=launcher_id)
            return HTTPResponse(status=204)

        return "/session_launchers/<launcher_id:ulid>", ["DELETE"], _delete

    def get_project_launchers(self) -> BlueprintFactoryResponse:
        """Get all launchers belonging to a project."""

        @authenticate(self.authenticator)
        async def _get_launcher(_: Request, user: base_models.APIUser, project_id: ULID) -> JSONResponse:
            launchers = await self.session_repo.get_project_launchers(user=user, project_id=project_id)
            return json(
                [
                    apispec.SessionLauncher.model_validate(item).model_dump(exclude_none=True, mode="json")
                    for item in launchers
                ]
            )

        return "/projects/<project_id:ulid>/session_launchers", ["GET"], _get_launcher
