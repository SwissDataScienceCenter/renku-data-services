"""Session blueprint."""

from dataclasses import dataclass
from pathlib import PurePosixPath

from sanic import HTTPResponse, Request
from sanic.response import JSONResponse
from sanic_ext import validate
from ulid import ULID

import renku_data_services.base_models as base_models
from renku_data_services.base_api.auth import authenticate, only_authenticated
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.base_models.validation import validated_json
from renku_data_services.session import apispec, models
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
            unsaved_environment = models.UnsavedEnvironment(
                name=body.name,
                description=body.description,
                container_image=body.container_image,
                default_url=body.default_url,
                port=body.port,
                working_directory=PurePosixPath(body.working_directory),
                mount_directory=PurePosixPath(body.mount_directory),
                uid=body.uid,
                gid=body.gid,
                environment_kind=models.EnvironmentKind.GLOBAL,
                command=body.command,
                args=body.args,
            )
            environment = await self.session_repo.insert_environment(user=user, new_environment=unsaved_environment)
            return validated_json(apispec.Environment, environment, 201)

        return "/environments", ["POST"], _post

    def patch(self) -> BlueprintFactoryResponse:
        """Partially update a specific session environment."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate(json=apispec.EnvironmentPatch)
        async def _patch(
            _: Request, user: base_models.APIUser, environment_id: ULID, body: apispec.EnvironmentPatch
        ) -> JSONResponse:
            body_dict = body.model_dump(exclude_none=True)
            environment = await self.session_repo.update_environment(
                user=user, environment_id=environment_id, **body_dict
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
            environment: str | models.UnsavedEnvironment
            if isinstance(body.environment, apispec.EnvironmentIdOnlyPost):
                environment = body.environment.id
            else:
                environment = models.UnsavedEnvironment(
                    name=body.environment.name,
                    description=body.environment.description,
                    container_image=body.environment.container_image,
                    default_url=body.environment.default_url,
                    port=body.environment.port,
                    working_directory=PurePosixPath(body.environment.working_directory),
                    mount_directory=PurePosixPath(body.environment.mount_directory),
                    uid=body.environment.uid,
                    gid=body.environment.gid,
                    environment_kind=models.EnvironmentKind(body.environment.environment_kind.value),
                    args=body.environment.args,
                    command=body.environment.command,
                )
            new_launcher = models.UnsavedSessionLauncher(
                project_id=ULID.from_str(body.project_id),
                name=body.name,
                description=body.description,
                environment=environment,
                resource_class_id=body.resource_class_id,
            )
            launcher = await self.session_repo.insert_launcher(user=user, new_launcher=new_launcher)
            return validated_json(apispec.SessionLauncher, launcher, 201)

        return "/session_launchers", ["POST"], _post

    def patch(self) -> BlueprintFactoryResponse:
        """Partially update a specific session launcher."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate(json=apispec.SessionLauncherPatch)
        async def _patch(
            _: Request, user: base_models.APIUser, launcher_id: ULID, body: apispec.SessionLauncherPatch
        ) -> JSONResponse:
            body_dict = body.model_dump(exclude_none=True, mode="json")
            async with self.session_repo.session_maker() as session, session.begin():
                current_launcher = await self.session_repo.get_launcher(user, launcher_id)
                new_env: models.UnsavedEnvironment | None = None
                if (
                    isinstance(body.environment, apispec.EnvironmentPatchInLauncher)
                    and current_launcher.environment.environment_kind == models.EnvironmentKind.GLOBAL
                    and body.environment.environment_kind == apispec.EnvironmentKind.CUSTOM
                ):
                    # This means that the global environment is being swapped for a custom one,
                    # so we have to create a brand new environment, but we have to validate here.
                    validated_env = apispec.EnvironmentPostInLauncher.model_validate(body_dict.pop("environment"))
                    new_env = models.UnsavedEnvironment(
                        name=validated_env.name,
                        description=validated_env.description,
                        container_image=validated_env.container_image,
                        default_url=validated_env.default_url,
                        port=validated_env.port,
                        working_directory=PurePosixPath(validated_env.working_directory),
                        mount_directory=PurePosixPath(validated_env.mount_directory),
                        uid=validated_env.uid,
                        gid=validated_env.gid,
                        environment_kind=models.EnvironmentKind(validated_env.environment_kind.value),
                        args=validated_env.args,
                        command=validated_env.command,
                    )
                launcher = await self.session_repo.update_launcher(
                    user=user, launcher_id=launcher_id, new_custom_environment=new_env, session=session, **body_dict
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
