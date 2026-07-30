"""Persisted logs blueprints."""

from collections.abc import Callable
from dataclasses import dataclass

from sanic import Request
from sanic.response import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from renku_data_services import base_models, errors
from renku_data_services.base_api.auth import authenticate, only_authenticated
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.base_api.misc import validate_query
from renku_data_services.base_models.validation import validated_json
from renku_data_services.persisted_logs import apispec, models
from renku_data_services.persisted_logs.db import (
    AmaltheaSessionPersistedLogsReadRepository,
    ImageBuildPersistedLogsReadRepository,
)


@dataclass(kw_only=True)
class PersistedLogsBP(CustomBlueprint):
    """Handlers for querying persisted logs."""

    session_logs_repo: AmaltheaSessionPersistedLogsReadRepository
    build_logs_repo: ImageBuildPersistedLogsReadRepository
    authenticator: base_models.Authenticator
    session_maker: Callable[..., AsyncSession]

    def get_session_logs(self) -> BlueprintFactoryResponse:
        """Get persisted sessions logs."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate_query(query=apispec.PersistedSessionLogsGetQuery)
        async def _get_session_logs(
            _: Request, user: base_models.APIUser, launcher_id: ULID, query: apispec.PersistedSessionLogsGetQuery
        ) -> JSONResponse:
            run_id = ULID.from_str(query.run_id) if query.run_id else None
            async with self.session_maker() as session, session.begin():
                result = await self.session_logs_repo.get_session_logs(
                    session=session,
                    user=user,
                    launcher_id=launcher_id,
                    run_id=run_id,
                    submission_id=query.submission_id,
                )
            if result is None:
                raise errors.MissingResourceError(
                    message=f"Session launcher with id '{launcher_id}' does not have persisted."
                )
            return validated_json(apispec.PersistedSessionLogs, result)

        return "/persisted_logs/sessions/<launcher_id:ulid>", ["GET"], _get_session_logs

    def get_session_runs(self) -> BlueprintFactoryResponse:
        """Get the session runs for a given session launcher."""

        @authenticate(self.authenticator)
        @only_authenticated
        async def _get_session_runs(_: Request, user: base_models.APIUser, launcher_id: ULID) -> JSONResponse:
            async with self.session_maker() as session, session.begin():
                session_runs = self.session_logs_repo.get_session_runs(
                    session=session, user=user, launcher_id=launcher_id
                )
                result: list[models.SessionRun] = []
                async for item in session_runs:
                    result.append(item)
            return validated_json(apispec.SessionRuns, result)

        return "/persisted_logs/sessions/<launcher_id:ulid>/runs", ["GET"], _get_session_runs

    def get_build_logs(self) -> BlueprintFactoryResponse:
        """Get persisted image build logs."""

        @authenticate(self.authenticator)
        @only_authenticated
        async def _get_build_logs(_: Request, user: base_models.APIUser, build_id: ULID) -> JSONResponse:
            async with self.session_maker() as session, session.begin():
                result = await self.build_logs_repo.get_build_logs(session=session, user=user, build_id=build_id)
            return validated_json(apispec.PersistedBuildLogs, dict(logs=result))

        return "/persisted_logs/builds/<build_id:ulid>", ["GET"], _get_build_logs
