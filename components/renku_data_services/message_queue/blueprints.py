"""Search/reprovisioning blueprint."""

from collections.abc import Callable
from dataclasses import dataclass

from sanic import HTTPResponse, Request, json
from sanic.response import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

import renku_data_services.base_models as base_models
from renku_data_services.authz.authz import Authz
from renku_data_services.base_api.auth import authenticate, only_admins
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.message_queue.core import reprovision
from renku_data_services.message_queue.db import EventRepository
from renku_data_services.namespace.db import GroupRepository
from renku_data_services.project.db import ProjectRepository
from renku_data_services.users.db import UserRepo


@dataclass(kw_only=True)
class SearchBP(CustomBlueprint):
    """Handlers for search."""

    authenticator: base_models.Authenticator
    session_maker: Callable[..., AsyncSession]
    event_repo: EventRepository
    user_repo: UserRepo
    group_repo: GroupRepository
    project_repo: ProjectRepository
    authz: Authz

    def post(self) -> BlueprintFactoryResponse:
        """Start a new reprovisioning."""

        @authenticate(self.authenticator)
        @only_admins
        async def _post(_: Request, user: base_models.APIUser) -> HTTPResponse:
            await reprovision(
                session_maker=self.session_maker,
                requested_by=user,
                event_repo=self.event_repo,
                user_repo=self.user_repo,
                group_repo=self.group_repo,
                project_repo=self.project_repo,
                authz=self.authz,
            )
            return HTTPResponse(status=201)

        return "/search/reprovision", ["POST"], _post

    def get_status(self) -> BlueprintFactoryResponse:
        """Get reprovisioning status."""

        @authenticate(self.authenticator)
        async def _get_status(_: Request, __: base_models.APIUser) -> JSONResponse | HTTPResponse:
            return json({"active": True}, 200)

        return "/search/reprovision", ["GET"], _get_status

    def delete(self) -> BlueprintFactoryResponse:
        """Stop reprovisioning (if any)."""

        @authenticate(self.authenticator)
        @only_admins
        async def _delete(_: Request, __: base_models.APIUser) -> HTTPResponse:
            # await self.project_repo.delete_project(user=user, project_id=ULID.from_str(project_id))
            return HTTPResponse(status=204)

        return "/search/reprovision", ["DELETE"], _delete
