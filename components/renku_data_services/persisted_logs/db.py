"""Adapters for persisted logs database classes."""

from collections.abc import AsyncIterator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from renku_data_services import base_models, errors
from renku_data_services.authz.authz import Authz, ResourceType
from renku_data_services.authz.models import Scope
from renku_data_services.persisted_logs import models
from renku_data_services.persisted_logs import orm as schemas
from renku_data_services.persisted_logs.constants import SESSION_MAIN_CONTAINER
from renku_data_services.session import orm as session_schemas


class AmaltheaSessionPersistedLogsReadRepository:
    """Repository for persisted logs of Amalthea sessions."""

    def __init__(self, authz: Authz) -> None:
        self.authz: Authz = authz

    async def get_session_logs(
        self,
        session: AsyncSession,
        user: base_models.APIUser,
        launcher_id: ULID,
        run_id: ULID | None = None,
        submission_id: str | None = None,
    ) -> models.PersistedSessionLogs | None:
        """Returns persisted session logs for the given launcher."""
        if not user.is_authenticated or not user.id:
            raise errors.UnauthorizedError(message="You have to be authenticated to perform this operation.")
        await self._check_session_launcher(session=session, user=user, launcher_id=launcher_id)
        session_run = await self._get_session_run(
            session=session, user_id=user.id, launcher_id=launcher_id, run_id=run_id, submission_id=submission_id
        )
        if session_run is None:
            return None

        logs_per_container = await self._get_logs_per_container(session=session, run_id=session_run.id)
        return models.PersistedSessionLogs(
            run=session_run,
            logs=logs_per_container,
        )

    async def get_session_runs(
        self,
        session: AsyncSession,
        user: base_models.APIUser,
        launcher_id: ULID,
    ) -> AsyncIterator[models.SessionRun]:
        """Returns the session runs for the given launcher."""
        if not user.is_authenticated or not user.id:
            raise errors.UnauthorizedError(message="You have to be authenticated to perform this operation.")
        await self._check_session_launcher(session=session, user=user, launcher_id=launcher_id)
        stmt = (
            select(schemas.SessionRunsORM)
            .where(schemas.SessionRunsORM.user_id == user.id)
            .where(schemas.SessionRunsORM.launcher_id == launcher_id)
            .order_by(schemas.SessionRunsORM.id.desc())
        )
        res = await session.stream_scalars(stmt)
        async for session_run_orm in res:
            yield session_run_orm.dump()

    async def _check_session_launcher(
        self, session: AsyncSession, user: base_models.APIUser, launcher_id: ULID
    ) -> None:
        """Check that the session launcher exists and the user has access to it."""
        stmt = select(session_schemas.SessionLauncherORM).where(session_schemas.SessionLauncherORM.id == launcher_id)
        res = await session.scalars(stmt)
        launcher_orm = res.one_or_none()
        authorized = (
            await self.authz.has_permission(user, ResourceType.project, launcher_orm.project_id, Scope.READ)
            if launcher_orm is not None
            else False
        )
        if not authorized or launcher_orm is None:
            raise errors.MissingResourceError(
                message=f"Session launcher with id '{launcher_id}' does not exist or you do not have access to it."
            )

    async def _get_session_run(
        self,
        session: AsyncSession,
        user_id: str,
        launcher_id: ULID,
        run_id: ULID | None = None,
        submission_id: str | None = None,
    ) -> models.SessionRun | None:
        """Get a specific session run from the persisted logs database.

        If no `run_id` is specified, then return the latest session run.
        """
        stmt = (
            select(schemas.SessionRunsORM)
            .where(schemas.SessionRunsORM.user_id == user_id)
            .where(schemas.SessionRunsORM.launcher_id == launcher_id)
            .order_by(schemas.SessionRunsORM.id.desc())
            .limit(1)
        )
        if run_id:
            stmt = stmt.where(schemas.SessionRunsORM.id == run_id)
        if submission_id:
            stmt = stmt.where(schemas.SessionRunsORM.submission_id == submission_id)
        res = await session.scalars(stmt)
        session_run_orm = res.one_or_none()
        if session_run_orm is None:
            return None
        return session_run_orm.dump()

    async def _get_logs_per_container(self, session: AsyncSession, run_id: ULID) -> models.SessionRunLogs:
        """Get the logs of a specific session run, organized by container."""
        # TODO: handle pagination?
        stmt = (
            select(schemas.AmaltheaSessionLogsORM)
            .where(schemas.AmaltheaSessionLogsORM.run_id == run_id)
            .order_by(schemas.AmaltheaSessionLogsORM.id.asc())
        )
        res = await session.stream_scalars(stmt)
        logs_per_container: dict[str, list[models.LogLine]] = dict()
        async for log_entry in res:
            container = log_entry.container
            logs = logs_per_container.get(container)
            if logs is None:
                logs = list[models.LogLine]()
                logs_per_container[container] = logs
            logs.append(models.LogLine(timestamp=log_entry.timestamp, log_line=log_entry.log_line))
        # Sort container by name, forcing "amalthea-session" to be the first item (main container)
        containers_set = set(logs_per_container.keys())
        containers: list[str] = list()
        if SESSION_MAIN_CONTAINER in containers_set:
            containers.append(SESSION_MAIN_CONTAINER)
            containers_set.remove(SESSION_MAIN_CONTAINER)
        containers.extend(sorted(containers_set))
        result: dict[str, list[models.LogLine]] = dict()
        for container in containers:
            result[container] = logs_per_container[container]
        return result


class AmaltheaSessionPersistedLogsRepository:
    """Repository for persisted logs of Amalthea sessions."""

    async def get_latest_log_timestamp(self, session: AsyncSession) -> int | None:
        """Returns the latest log timestamp."""
        stmt = (
            select(schemas.AmaltheaSessionLogsORM.timestamp)
            .select_from(schemas.AmaltheaSessionLogsORM)
            .order_by(schemas.AmaltheaSessionLogsORM.timestamp.desc())
            .limit(1)
        )
        res = await session.scalars(stmt)
        timestamp = res.one_or_none()
        return timestamp

    async def insert_session_logs(
        self, session: AsyncSession, logs_stream: AsyncIterator[models.UnsavedLogLine]
    ) -> models.InsertLogsResult:
        """Insert sessions logs into the persisted logs database."""
        log_count = 0
        last_timestamp = 0
        async for log in logs_stream:
            log_count += 1
            if log.timestamp > last_timestamp:
                last_timestamp = log.timestamp

            existing_log_res = await session.scalars(
                select(schemas.AmaltheaSessionLogsORM.id).where(schemas.AmaltheaSessionLogsORM.id == log.id)
            )
            existing_log_orm = existing_log_res.one_or_none()
            if existing_log_orm:
                continue

            # NOTE: temporary code for finding a session run for jobs (one per submission)
            run_id = log.run_id
            if log.submission_id:
                session_run_res = await session.scalars(
                    select(schemas.SessionRunsORM)
                    .where(schemas.SessionRunsORM.user_id == log.user_id)
                    .where(schemas.SessionRunsORM.submission_id == log.submission_id)
                )
                session_run_orm = session_run_res.one_or_none()
                if session_run_orm is None:
                    run_id = ULID()
                    session_run_orm = schemas.SessionRunsORM(
                        id=run_id,
                        user_id=log.user_id,
                        launch_id=log.launch_id,
                        launcher_id=log.launcher_id,
                        submission_id=log.submission_id,
                    )
                    session.add(session_run_orm)
                    await session.flush()
                else:
                    run_id = session_run_orm.id
            else:
                session_run_res = await session.scalars(
                    select(schemas.SessionRunsORM).where(schemas.SessionRunsORM.id == log.run_id)
                )
                session_run_orm = session_run_res.one_or_none()
                if session_run_orm is None:
                    session_run_orm = schemas.SessionRunsORM(
                        id=log.run_id,
                        user_id=log.user_id,
                        launch_id=log.launch_id,
                        launcher_id=log.launcher_id,
                        submission_id=log.submission_id,
                    )
                    session.add(session_run_orm)
                    await session.flush()

            log_orm = schemas.AmaltheaSessionLogsORM(
                id=log.id,
                run_id=run_id,
                container=log.container,
                timestamp=log.timestamp,
                log_line=log.log_line,
            )
            session.add(log_orm)
            await session.flush()
        return models.InsertLogsResult(log_count=log_count, last_timestamp=last_timestamp)
