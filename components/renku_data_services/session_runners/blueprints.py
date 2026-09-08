"""Session runners blueprints."""

from collections.abc import Callable
from dataclasses import dataclass

from sanic import Request
from sanic.response import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from renku_data_services import base_models
from renku_data_services.base_api.auth import authenticate, only_authenticated
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.base_api.misc import validate
from renku_data_services.base_models.validation import validated_json
from renku_data_services.session_runners import apispec
from renku_data_services.session_runners.core import validate_unsaved_session_runner
from renku_data_services.session_runners.db import SessionRunnersRepository


@dataclass(kw_only=True)
class SessionRunnersBP(CustomBlueprint):
    """Handlers for session runners."""

    session_runners_repo: SessionRunnersRepository
    authenticator: base_models.Authenticator
    session_maker: Callable[..., AsyncSession]

    def post_session_runner(self) -> BlueprintFactoryResponse:
        """Create a new session runner."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate(query=apispec.SessionRunnerPost)
        async def _post_session_runner(
            _: Request, user: base_models.APIUser, body: apispec.SessionRunnerPost
        ) -> JSONResponse:
            new_runner = validate_unsaved_session_runner(runner=body)
            async with self.session_maker() as session, session.begin():
                runner = await self.session_runners_repo.insert_runner(session=session, user=user, runner=new_runner)
            return validated_json(apispec.SessionRunner, runner, status=201)

        return "/session_runners", ["POST"], _post_session_runner
