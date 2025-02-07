"""Session blueprint."""

from dataclasses import dataclass

from sanic import HTTPResponse, Request
from sanic.response import JSONResponse
from sanic_ext import validate
from ulid import ULID

from renku_data_services import base_models, errors
from renku_data_services.base_api.auth import authenticate, only_authenticated
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.base_api.misc import validate_query
from renku_data_services.base_models.validation import validated_json
from renku_data_services.session import apispec, models
from renku_data_services.session.core import (
    validate_environment_patch,
    validate_session_launcher_patch,
    validate_unsaved_environment,
    validate_unsaved_session_launcher,
)
from renku_data_services.session.db import SessionRepository


@dataclass(kw_only=True)
class EnvironmentsBP(CustomBlueprint):
    """Handlers for manipulating session environments."""

    session_repo: SessionRepository
    authenticator: base_models.Authenticator

    def get_all(self) -> BlueprintFactoryResponse:
        """List all session environments."""

        @validate_query(query=apispec.GetEnvironmentParams)
        async def _get_all(_: Request, query: apispec.GetEnvironmentParams) -> JSONResponse:
            environments = await self.session_repo.get_environments(include_archived=query.include_archived)
            return validated_json(apispec.EnvironmentList, environments)

        return "/environments", ["GET"], _get_all

    def get_one(self) -> BlueprintFactoryResponse:
        """Get a specific session environment."""

        async def _get_one(_: Request, environment_id: ULID) -> JSONResponse:
            environment = await self.session_repo.get_environment(environment_id=environment_id)
            return validated_json(apispec.Environment, environment)

        return "/environments/<environment_id:ulid>", ["GET"], _get_one

    def post(self) -> BlueprintFactoryResponse:
        """Create a new session environment."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate(json=apispec.EnvironmentPost)
        async def _post(_: Request, user: base_models.APIUser, body: apispec.EnvironmentPost) -> JSONResponse:
            new_environment = validate_unsaved_environment(body, models.EnvironmentKind.GLOBAL)
            environment = await self.session_repo.insert_environment(user=user, environment=new_environment)
            return validated_json(apispec.Environment, environment, status=201)

        return "/environments", ["POST"], _post

    def patch(self) -> BlueprintFactoryResponse:
        """Partially update a specific session environment."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate(json=apispec.EnvironmentPatch)
        async def _patch(
            _: Request, user: base_models.APIUser, environment_id: ULID, body: apispec.EnvironmentPatch
        ) -> JSONResponse:
            environment_patch = validate_environment_patch(body)
            environment = await self.session_repo.update_environment(
                user=user, environment_id=environment_id, patch=environment_patch
            )
            return validated_json(apispec.Environment, environment)

        return "/environments/<environment_id:ulid>", ["PATCH"], _patch

    def delete(self) -> BlueprintFactoryResponse:
        """Delete a specific session environment."""

        @authenticate(self.authenticator)
        @only_authenticated
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
            return validated_json(apispec.SessionLaunchersList, launchers)

        return "/session_launchers", ["GET"], _get_all

    def get_one(self) -> BlueprintFactoryResponse:
        """Get a specific session launcher."""

        @authenticate(self.authenticator)
        async def _get_one(_: Request, user: base_models.APIUser, launcher_id: ULID) -> JSONResponse:
            launcher = await self.session_repo.get_launcher(user=user, launcher_id=launcher_id)
            return validated_json(apispec.SessionLauncher, launcher)

        return "/session_launchers/<launcher_id:ulid>", ["GET"], _get_one

    def post(self) -> BlueprintFactoryResponse:
        """Create a new session launcher."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate(json=apispec.SessionLauncherPost)
        async def _post(_: Request, user: base_models.APIUser, body: apispec.SessionLauncherPost) -> JSONResponse:
            new_launcher = validate_unsaved_session_launcher(body)
            launcher = await self.session_repo.insert_launcher(user=user, launcher=new_launcher)
            return validated_json(apispec.SessionLauncher, launcher, status=201)

        return "/session_launchers", ["POST"], _post

    def patch(self) -> BlueprintFactoryResponse:
        """Partially update a specific session launcher."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate(json=apispec.SessionLauncherPatch)
        async def _patch(
            _: Request, user: base_models.APIUser, launcher_id: ULID, body: apispec.SessionLauncherPatch
        ) -> JSONResponse:
            async with self.session_repo.session_maker() as session, session.begin():
                current_launcher = await self.session_repo.get_launcher(user, launcher_id)
                launcher_patch = validate_session_launcher_patch(body, current_launcher)
                launcher = await self.session_repo.update_launcher(
                    user=user, launcher_id=launcher_id, patch=launcher_patch, session=session
                )
            return validated_json(apispec.SessionLauncher, launcher)

        return "/session_launchers/<launcher_id:ulid>", ["PATCH"], _patch

    def delete(self) -> BlueprintFactoryResponse:
        """Delete a specific session launcher."""

        @authenticate(self.authenticator)
        @only_authenticated
        async def _delete(_: Request, user: base_models.APIUser, launcher_id: ULID) -> HTTPResponse:
            await self.session_repo.delete_launcher(user=user, launcher_id=launcher_id)
            return HTTPResponse(status=204)

        return "/session_launchers/<launcher_id:ulid>", ["DELETE"], _delete

    def get_project_launchers(self) -> BlueprintFactoryResponse:
        """Get all launchers belonging to a project."""

        @authenticate(self.authenticator)
        async def _get_launcher(_: Request, user: base_models.APIUser, project_id: ULID) -> JSONResponse:
            launchers = await self.session_repo.get_project_launchers(user=user, project_id=project_id)
            return validated_json(apispec.SessionLaunchersList, launchers)

        return "/projects/<project_id:ulid>/session_launchers", ["GET"], _get_launcher


@dataclass(kw_only=True)
class BuildsBP(CustomBlueprint):
    """Handlers for manipulating container image builds."""

    # session_repo: SessionRepository
    authenticator: base_models.Authenticator

    def get_one(self) -> BlueprintFactoryResponse:
        """Get a specific container image build."""

        @authenticate(self.authenticator)
        async def _get_one(_: Request, user: base_models.APIUser, build_id: ULID) -> HTTPResponse:
            raise errors.ProgrammingError(message="Not implemented")

        return "/builds/<build_id:ulid>", ["GET"], _get_one

    def post(self) -> BlueprintFactoryResponse:
        """Create a new container image build."""

        @authenticate(self.authenticator)
        async def _post(_: Request, user: base_models.APIUser) -> HTTPResponse:
            raise errors.ProgrammingError(message="Not implemented")

        return "/builds", ["POST"], _post

    def get_environment_builds(self) -> BlueprintFactoryResponse:
        """Get all container image builds belonging to a session environment."""

        @authenticate(self.authenticator)
        async def _get_environment_builds(_: Request, user: base_models.APIUser, environment_id: ULID) -> JSONResponse:
            raise errors.ProgrammingError(message="Not implemented")

        return "/environments/<environment_id:ulid>/builds", ["GET"], _get_environment_builds
