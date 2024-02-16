"""Session blueprint."""

from dataclasses import dataclass
from datetime import datetime, timezone

from sanic import HTTPResponse, Request, json
from sanic_ext import validate

import renku_data_services.base_models as base_models
from renku_data_services.base_api.auth import authenticate, only_authenticated
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.errors import errors
from renku_data_services.session import apispec, models
from renku_data_services.session.db import SessionRepository
from renku_data_services.users.db import UserRepo

# from renku_data_services.project.db import ProjectRepository


@dataclass(kw_only=True)
class SessionsBP(CustomBlueprint):
    """Handlers for manipulating sessions."""

    session_repo: SessionRepository
    user_repo: UserRepo
    authenticator: base_models.Authenticator

    def get_all(self) -> BlueprintFactoryResponse:
        """List all sessions."""

        @authenticate(self.authenticator)
        async def _get_all(_: Request, *, user: base_models.APIUser):
            sessions = await self.session_repo.get_sessions(user=user)
            return json(
                [apispec.Session.model_validate(p).model_dump(exclude_none=True, mode="json") for p in sessions], 200
            )

        return "/sessions", ["GET"], _get_all

    def post(self) -> BlueprintFactoryResponse:
        """Create a new session."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate(json=apispec.SessionPost)
        async def _post(_: Request, *, user: base_models.APIUser, body: apispec.SessionPost):
            data = body.model_dump(exclude_none=True)
            user_id = user.id
            if not user_id:
                raise errors.ValidationError(message="Cannot create session for anonymous users")
            # NOTE: Set ``creation_date`` to override possible value set by users
            data["creation_date"] = datetime.now(timezone.utc).replace(microsecond=0)
            data["created_by"] = models.Member(id=user_id)
            session = models.Session.from_dict(data)
            result = await self.session_repo.insert_session(user=user, session=session)
            return json(apispec.Session.model_validate(result).model_dump(exclude_none=True, mode="json"), 201)

        return "/sessions", ["POST"], _post

    def get_one(self) -> BlueprintFactoryResponse:
        """Get a specific session."""

        @authenticate(self.authenticator)
        async def _get_one(_: Request, *, user: base_models.APIUser, session_id: str):
            session = await self.session_repo.get_session(user=user, session_id=session_id)
            return json(apispec.Session.model_validate(session).model_dump(exclude_none=True, mode="json"))

        return "/sessions/<session_id>", ["GET"], _get_one

    def delete(self) -> BlueprintFactoryResponse:
        """Delete a specific session."""

        @authenticate(self.authenticator)
        @only_authenticated
        async def _delete(_: Request, *, user: base_models.APIUser, session_id: str):
            await self.session_repo.delete_session(user=user, session_id=session_id)
            return HTTPResponse(status=204)

        return "/sessions/<session_id>", ["DELETE"], _delete

    def patch(self) -> BlueprintFactoryResponse:
        """Partially update a specific session."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate(json=apispec.SessionPatch)
        async def _patch(_: Request, *, user: base_models.APIUser, session_id: str, body: apispec.SessionPatch):
            body_dict = body.model_dump(exclude_none=True)

            updated_session = await self.session_repo.update_session(user=user, session_id=session_id, **body_dict)

            return json(apispec.Session.model_validate(updated_session).model_dump(exclude_none=True, mode="json"))

        return "/sessions/<session_id>", ["PATCH"], _patch
