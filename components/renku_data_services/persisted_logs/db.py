"""Adapters for persisted logs database classes."""

from collections.abc import AsyncIterator, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from renku_data_services import base_models, errors
from renku_data_services.app_config import logging
from renku_data_services.authz.authz import Authz, ResourceType
from renku_data_services.authz.models import Scope
from renku_data_services.persisted_logs import models
from renku_data_services.persisted_logs import orm as schemas
from renku_data_services.session import orm as session_schemas

logger = logging.getLogger(__name__)


class AmaltheaSessionPersistedLogsReadRepository:
    """Repository for persisted logs of Amalthea sessions."""

    def __init__(self, authz: Authz) -> None:
        self.authz: Authz = authz

    async def get_session_logs(self, session: AsyncSession, user: base_models.APIUser, launcher_id: ULID) -> None:
        """Returns persisted session logs for the given launcher."""
        if not user.is_authenticated or not user.id:
            raise errors.UnauthorizedError(message="You have to be authenticated to perform this operation.")
        await self._check_session_launcher(session=session, user=user, launcher_id=launcher_id)
        latest_run = await self._get_session_run(session=session, user_id=user.id, launcher_id=launcher_id)

        # TODO
        if latest_run is None:
            return

        logger.info(f"latest_run = {str(latest_run)}")

        containers = await self._get_containers(session=session, run_id=latest_run)

        logger.info(f"containers = {str(containers)}")

        # TODO
        pass

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

    async def _get_session_run(self, session: AsyncSession, user_id: str, launcher_id: ULID) -> ULID | None:
        """Get a specific session run from the persisted logs database."""
        stmt = (
            select(schemas.SessionRunsORM)
            .where(schemas.SessionRunsORM.user_id == user_id)
            .where(schemas.SessionRunsORM.launcher_id == launcher_id)
            .order_by(schemas.SessionRunsORM.id.desc())
            .limit(1)
        )
        res = await session.scalars(stmt)
        session_run = res.one_or_none()
        if session_run is None:
            return None
        # TODO: return a model instance with .dump()
        return session_run.id

    async def _get_containers(self, session: AsyncSession, run_id: ULID) -> Sequence[str]:
        """Get the list of pod containers from the persisted logs database."""
        stmt = (
            select(schemas.AmaltheaSessionLogsORM.container.distinct())
            .select_from(schemas.AmaltheaSessionLogsORM)
            .where(schemas.AmaltheaSessionLogsORM.run_id == run_id)
            .order_by(schemas.AmaltheaSessionLogsORM.container)
        )
        res = await session.scalars(stmt)
        containers = res.all()
        return containers


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
                logger.info(f"Skipping log line {log.id}")
                continue

            logger.info(f"Processing log line {log}")

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
                run_id=log.run_id,
                container=log.container,
                timestamp=log.timestamp,
                log_line=log.log_line,
            )
            session.add(log_orm)
            await session.flush()
        return models.InsertLogsResult(log_count=log_count, last_timestamp=last_timestamp)
