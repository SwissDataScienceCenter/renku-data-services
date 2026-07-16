"""Adapters for persisted logs database classes."""

from collections.abc import AsyncIterator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from renku_data_services.app_config import logging
from renku_data_services.persisted_logs import models
from renku_data_services.persisted_logs import orm as schemas

logger = logging.getLogger(__name__)


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
