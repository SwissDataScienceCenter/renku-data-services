"""Session blueprint."""

from dataclasses import dataclass

from sanic import HTTPResponse, Request, json
from sanic_ext import validate

import renku_data_services.base_models as base_models
from renku_data_services.base_api.auth import authenticate
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.session import apispec
from renku_data_services.session.db import SessionRepository


@dataclass(kw_only=True)
class SessionEnvironmentsBP(CustomBlueprint):
    """Handlers for manipulating session environments."""

    session_repo: SessionRepository
    authenticator: base_models.Authenticator

    def get_all(self) -> BlueprintFactoryResponse:
        """List all session environments."""

        async def _get_all(_: Request):
            environments = await self.session_repo.get_environments()
            return json(
                [apispec.Environment.model_validate(e).model_dump(exclude_none=True, mode="json") for e in environments]
            )

        return "/environments", ["GET"], _get_all

    def get_one(self) -> BlueprintFactoryResponse:
        """Get a specific session environment."""

        async def _get_one(_: Request, environment_id: str):
            environment = await self.session_repo.get_environment(environment_id=environment_id)
            return json(apispec.Environment.model_validate(environment).model_dump(exclude_none=True, mode="json"))

        return "/environments/<environment_id>", ["GET"], _get_one

    def post(self) -> BlueprintFactoryResponse:
        """Create a new session environment."""

        @authenticate(self.authenticator)
        @validate(json=apispec.EnvironmentPost)
        async def _post(_: Request, body: apispec.EnvironmentPost, user: base_models.APIUser):
            environment = await self.session_repo.insert_environment(user=user, new_environment=body)
            return json(apispec.Environment.model_validate(environment).model_dump(exclude_none=True, mode="json"), 201)

        return "/environments", ["POST"], _post

    def patch(self) -> BlueprintFactoryResponse:
        """Partially update a specific session environment."""

        @authenticate(self.authenticator)
        @validate(json=apispec.EnvironmentPatch)
        async def _patch(_: Request, environment_id: str, body: apispec.EnvironmentPatch, user: base_models.APIUser):
            body_dict = body.model_dump(exclude_none=True)
            environment = await self.session_repo.update_environment(
                user=user, environment_id=environment_id, **body_dict
            )
            return json(apispec.Environment.model_validate(environment).model_dump(exclude_none=True, mode="json"))

        return "/environments/<environment_id>", ["PATCH"], _patch

    def delete(self) -> BlueprintFactoryResponse:
        """Delete a specific session environment."""

        @authenticate(self.authenticator)
        async def _delete(_: Request, environment_id: str, user: base_models.APIUser):
            await self.session_repo.delete_environment(user=user, environment_id=environment_id)
            return HTTPResponse(status=204)

        return "/environments/<environment_id>", ["DELETE"], _delete


@dataclass(kw_only=True)
class SessionLaunchersBP(CustomBlueprint):
    """Handlers for manipulating session launcher."""

    session_repo: SessionRepository
    authenticator: base_models.Authenticator

    def get_all(self) -> BlueprintFactoryResponse:
        """List all session launcher visible to user."""

        @authenticate(self.authenticator)
        async def _get_all(_: Request, user: base_models.APIUser):
            launchers = await self.session_repo.get_launchers(user=user)
            return json(
                [apispec.Launcher.model_validate(item).model_dump(exclude_none=True, mode="json") for item in launchers]
            )

        return "/session_launchers", ["GET"], _get_all

    def get_one(self) -> BlueprintFactoryResponse:
        """Get a specific session launcher."""

        @authenticate(self.authenticator)
        async def _get_one(_: Request, launcher_id: str, user: base_models.APIUser):
            launcher = await self.session_repo.get_launcher(user=user, launcher_id=launcher_id)
            return json(apispec.Launcher.model_validate(launcher).model_dump(exclude_none=True, mode="json"))

        return "/session_launchers/<launcher_id>", ["GET"], _get_one

    def post(self) -> BlueprintFactoryResponse:
        """Create a new session launcher."""

        @authenticate(self.authenticator)
        @validate(json=apispec.LauncherPost)
        async def _post(_: Request, body: apispec.LauncherPost, user: base_models.APIUser):
            launcher = await self.session_repo.insert_launcher(user=user, new_launcher=body)
            return json(apispec.Launcher.model_validate(launcher).model_dump(exclude_none=True, mode="json"), 201)

        return "/session_launchers", ["POST"], _post

    def patch(self) -> BlueprintFactoryResponse:
        """Partially update a specific session launcher."""

        @authenticate(self.authenticator)
        @validate(json=apispec.LauncherPatch)
        async def _patch(_: Request, launcher_id: str, body: apispec.LauncherPatch, user: base_models.APIUser):
            body_dict = body.model_dump(exclude_none=True)
            launcher = await self.session_repo.update_launcher(user=user, launcher_id=launcher_id, **body_dict)
            return json(apispec.Launcher.model_validate(launcher).model_dump(exclude_none=True, mode="json"))

        return "/session_launchers/<launcher_id>", ["PATCH"], _patch

    def delete(self) -> BlueprintFactoryResponse:
        """Delete a specific session launcher."""

        @authenticate(self.authenticator)
        async def _delete(_: Request, launcher_id: str, user: base_models.APIUser):
            await self.session_repo.delete_launcher(user=user, launcher_id=launcher_id)
            return HTTPResponse(status=204)

        return "/session_launchers/<launcher_id>", ["DELETE"], _delete

    def get_project_launchers(self) -> BlueprintFactoryResponse:
        """Get all launchers belonging to a project."""

        @authenticate(self.authenticator)
        async def _get_launcher(_: Request, project_id: str, user: base_models.APIUser):
            launchers = await self.session_repo.get_project_launchers(user=user, project_id=project_id)
            return json(
                [apispec.Launcher.model_validate(item).model_dump(exclude_none=True, mode="json") for item in launchers]
            )

        return "/projects/<project_id>/session_launchers", ["GET"], _get_launcher


# @dataclass(kw_only=True)
# class SessionsBP(CustomBlueprint):
#     """Handlers for manipulating sessions."""

#     session_repo: SessionRepository
#     user_repo: UserRepo
#     authenticator: base_models.Authenticator

#     def get_all(self) -> BlueprintFactoryResponse:
#         """List all sessions."""

#         @authenticate(self.authenticator)
#         async def _get_all(_: Request, *, user: base_models.APIUser):
#             sessions = await self.session_repo.get_sessions(user=user)
#             return json(
#                 [apispec.Session.model_validate(p).model_dump(exclude_none=True, mode="json") for p in sessions], 200
#             )

#         return "/sessions", ["GET"], _get_all

#     def post(self) -> BlueprintFactoryResponse:
#         """Create a new session."""

#         @authenticate(self.authenticator)
#         @only_authenticated
#         @validate(json=apispec.SessionPost)
#         async def _post(_: Request, *, user: base_models.APIUser, body: apispec.SessionPost):
#             data = body.model_dump(exclude_none=True)
#             user_id = user.id
#             if not user_id:
#                 raise errors.ValidationError(message="Cannot create session for anonymous users")
#             # NOTE: Set ``creation_date`` to override possible value set by users
#             data["creation_date"] = datetime.now(timezone.utc).replace(microsecond=0)
#             data["created_by"] = models.Member(id=user_id)
#             session = models.Session.from_dict(data)
#             result = await self.session_repo.insert_session(user=user, session=session)
#             return json(apispec.Session.model_validate(result).model_dump(exclude_none=True, mode="json"), 201)

#         return "/sessions", ["POST"], _post

#     def get_one(self) -> BlueprintFactoryResponse:
#         """Get a specific session."""

#         @authenticate(self.authenticator)
#         async def _get_one(_: Request, *, user: base_models.APIUser, session_id: str):
#             session = await self.session_repo.get_session(user=user, session_id=session_id)
#             return json(apispec.Session.model_validate(session).model_dump(exclude_none=True, mode="json"))

#         return "/sessions/<session_id>", ["GET"], _get_one

#     def delete(self) -> BlueprintFactoryResponse:
#         """Delete a specific session."""

#         @authenticate(self.authenticator)
#         @only_authenticated
#         async def _delete(_: Request, *, user: base_models.APIUser, session_id: str):
#             await self.session_repo.delete_session(user=user, session_id=session_id)
#             return HTTPResponse(status=204)

#         return "/sessions/<session_id>", ["DELETE"], _delete

#     def patch(self) -> BlueprintFactoryResponse:
#         """Partially update a specific session."""

#         @authenticate(self.authenticator)
#         @only_authenticated
#         @validate(json=apispec.SessionPatch)
#         async def _patch(_: Request, *, user: base_models.APIUser, session_id: str, body: apispec.SessionPatch):
#             body_dict = body.model_dump(exclude_none=True)

#             updated_session = await self.session_repo.update_session(user=user, session_id=session_id, **body_dict)

#             return json(apispec.Session.model_validate(updated_session).model_dump(exclude_none=True, mode="json"))

#         return "/sessions/<session_id>", ["PATCH"], _patch
