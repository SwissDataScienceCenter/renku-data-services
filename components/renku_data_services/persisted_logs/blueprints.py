"""Persisted logs blueprints."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sanic import Request
from sanic.response import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from renku_data_services import base_models, errors
from renku_data_services.base_api.auth import authenticate, only_authenticated
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.base_models.validation import validated_json
from renku_data_services.persisted_logs import apispec, models
from renku_data_services.persisted_logs.db import AmaltheaSessionPersistedLogsReadRepository


@dataclass(kw_only=True)
class PersistedLogsBP(CustomBlueprint):
    """Handlers for querying persisted logs."""

    session_logs_repo: AmaltheaSessionPersistedLogsReadRepository
    authenticator: base_models.Authenticator
    session_maker: Callable[..., AsyncSession]

    def get_session_logs(self) -> BlueprintFactoryResponse:
        """Get persisted sessions logs."""

        @authenticate(self.authenticator)
        @only_authenticated
        async def _get_session_logs(_: Request, user: base_models.APIUser, launcher_id: ULID) -> JSONResponse:
            async with self.session_maker() as session, session.begin():
                result = await self.session_logs_repo.get_session_logs(
                    session=session, user=user, launcher_id=launcher_id
                )
            if result is None:
                raise errors.MissingResourceError(
                    message=f"Session launcher with id '{launcher_id}' does not have logs yet."
                )
            return validated_json(apispec.PersistedSessionLogs, self._dump_persisted_session_logs(result))

        return "/persisted_logs/sessions/<launcher_id:ulid>", ["GET"], _get_session_logs

    @staticmethod
    def _dump_persisted_session_logs(session_log: models.PersistedSessionLogs) -> dict[str, Any]:
        """Dump persisted session logs for API responses."""
        return dict(
            run=PersistedLogsBP._dump_session_run(session_log.run),
            logs=PersistedLogsBP._dump_session_run_logs(session_log.logs),
        )

    @staticmethod
    def _dump_session_run(session_run: models.SessionRun) -> dict[str, Any]:
        """Dump a session run for API responses."""
        # NOTE: omit the "user_id" field
        return dict(
            id=session_run.id,
            launch_id=session_run.launch_id,
            launcher_id=session_run.launcher_id,
            submission_id=session_run.submission_id,
        )

    @staticmethod
    def _dump_session_run_logs(logs: models.SessionRunLogs) -> list[dict[str, Any]]:
        """Dump the logs of a session run, organized by pod container, for API responses."""
        return list(dict(container=container, logs=log_lines) for container, log_lines in logs.items())
