"""Adapters for persisted logs database classes."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import delete, select
from sqlalchemy.exc import DatabaseError
from sqlalchemy.ext.asyncio import AsyncScalarResult, AsyncSession
from ulid import ULID

from renku_data_services import base_models, errors
from renku_data_services.app_config import logging
from renku_data_services.authz.authz import Authz, ResourceType
from renku_data_services.authz.models import Scope
from renku_data_services.persisted_logs import models
from renku_data_services.persisted_logs import orm as schemas
from renku_data_services.persisted_logs.constants import BUILD_MAIN_CONTAINER, SESSION_MAIN_CONTAINER
from renku_data_services.repositories import models as repo_models
from renku_data_services.session import models as session_models
from renku_data_services.session import orm as session_schemas

if TYPE_CHECKING:
    from renku_data_services.repositories.db import GitRepositoriesRepository
    from renku_data_services.session.config import BuildsConfig
logger = logging.getLogger(__name__)


class AmaltheaSessionPersistedLogsReadRepository:
    """Repository for reading persisted logs of Amalthea sessions."""

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
            select(schemas.SessionRunORM)
            .where(schemas.SessionRunORM.user_id == user.id)
            .where(schemas.SessionRunORM.launcher_id == launcher_id)
            .order_by(schemas.SessionRunORM.id.desc())
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
            select(schemas.SessionRunORM)
            .where(schemas.SessionRunORM.user_id == user_id)
            .where(schemas.SessionRunORM.launcher_id == launcher_id)
            .order_by(schemas.SessionRunORM.id.desc())
            .limit(1)
        )
        if run_id:
            stmt = stmt.where(schemas.SessionRunORM.id == run_id)
        if submission_id:
            stmt = stmt.where(schemas.SessionRunORM.submission_id == submission_id)
        res = await session.scalars(stmt)
        session_run_orm = res.one_or_none()
        if session_run_orm is None:
            return None
        return session_run_orm.dump()

    async def _get_logs_per_container(self, session: AsyncSession, run_id: ULID) -> Sequence[models.ContainerLogs]:
        """Get the logs of a specific session run, organized by container."""
        # TODO: handle pagination?
        stmt = (
            select(schemas.AmaltheaSessionLogORM)
            .where(schemas.AmaltheaSessionLogORM.run_id == run_id)
            .order_by(schemas.AmaltheaSessionLogORM.id.asc())
        )
        res = await session.stream_scalars(stmt)
        # Sort logs by container name, forcing "amalthea-session" to be the first item (main container)
        return await _sort_logs_per_container(res, main_container=SESSION_MAIN_CONTAINER)


class AmaltheaSessionPersistedLogsWriteRepository:
    """Repository for writing persisted logs of Amalthea sessions.

    The write side is performed as a background task and does not access authz.
    """

    async def get_latest_log_timestamp(self, session: AsyncSession) -> int | None:
        """Returns the latest log timestamp."""
        stmt = (
            select(schemas.AmaltheaSessionLogORM.timestamp)
            .select_from(schemas.AmaltheaSessionLogORM)
            .order_by(schemas.AmaltheaSessionLogORM.timestamp.desc())
            .limit(1)
        )
        res = await session.scalars(stmt)
        timestamp = res.one_or_none()
        return timestamp

    async def insert_session_logs(
        self, session: AsyncSession, logs_stream: AsyncIterator[models.UnsavedSessionLogLine]
    ) -> models.LogStreamMetadata:
        """Insert sessions logs into the persisted logs database."""
        log_count = 0
        last_timestamp = 0
        async for log in logs_stream:
            log_count += 1
            if log.timestamp > last_timestamp:
                last_timestamp = log.timestamp
            try:
                await self._insert_log_line(session=session, log=log)
            except DatabaseError as err:
                logger.warning(f"Could not process log line {log.id}: {err}")

        return models.LogStreamMetadata(log_count=log_count, last_timestamp=last_timestamp)

    async def delete_expired_session_logs(self, session: AsyncSession, before: datetime) -> int:
        """Remove expired session logs from the database."""
        nano_ts = models.NanoTimestamp.from_datetime(before)
        delete_logs_stmt = delete(schemas.AmaltheaSessionLogORM).where(
            schemas.AmaltheaSessionLogORM.timestamp < nano_ts
        )
        res = await session.execute(delete_logs_stmt)
        deleted_logs_count = res.rowcount

        # Remove orphaned session runs
        stmt = (
            select(schemas.SessionRunORM.id)
            .join(
                schemas.AmaltheaSessionLogORM,
                schemas.SessionRunORM.id == schemas.AmaltheaSessionLogORM.run_id,
                isouter=True,  # isouter makes it a left-join, not an outer join
            )
            .where(schemas.AmaltheaSessionLogORM.id.is_(None))
        )
        session_runs_res = await session.scalars(stmt)
        session_run_ids = session_runs_res.all()
        await session.execute(delete(schemas.SessionRunORM).where(schemas.SessionRunORM.id.in_(session_run_ids)))

        return deleted_logs_count

    async def _insert_log_line(self, session: AsyncSession, log: models.UnsavedSessionLogLine) -> bool:
        """Insert a single session log line into the persisted logs database.

        Returns true if the log line was inserted into the database and false otherwise (the log line already exists).
        """
        existing_log_res = await session.scalars(
            select(schemas.AmaltheaSessionLogORM.id).where(schemas.AmaltheaSessionLogORM.id == log.id)
        )
        existing_log_orm = existing_log_res.one_or_none()
        if existing_log_orm:
            return False

        session_run_res = await session.scalars(
            select(schemas.SessionRunORM).where(schemas.SessionRunORM.id == log.run_id)
        )
        session_run_orm = session_run_res.one_or_none()
        if session_run_orm is None:
            async with session.begin_nested():
                session_run_orm = schemas.SessionRunORM(
                    id=log.run_id,
                    user_id=log.user_id,
                    session_uid=log.session_uid,
                    launcher_id=log.launcher_id,
                    submission_id=log.submission_id,
                )
                session.add(session_run_orm)
                await session.flush()

        log_orm = schemas.AmaltheaSessionLogORM(
            id=log.id,
            run_id=log.run_id,
            container=log.container,
            timestamp=log.timestamp,
            log_line=log.log_line,
        )
        session.add(log_orm)
        await session.flush()
        return True


class ImageBuildPersistedLogsReadRepository:
    """Repository for reading persisted logs of image builds."""

    def __init__(
        self,
        authz: Authz,
        builds_config: BuildsConfig,
        git_repositories_repo: GitRepositoriesRepository,
    ) -> None:
        self.authz: Authz = authz
        self.builds_config = builds_config
        self.git_repositories_repo = git_repositories_repo

    async def get_build_logs(
        self, session: AsyncSession, user: base_models.APIUser, build_id: ULID
    ) -> Sequence[models.ContainerLogs]:
        """Returns persisted session logs for the given image build."""
        if not user.is_authenticated or not user.id:
            raise errors.UnauthorizedError(message="You have to be authenticated to perform this operation.")
        await self._check_build(session=session, user=user, build_id=build_id)
        logs_per_container = await self._get_logs_per_container(session=session, build_id=build_id)
        return logs_per_container

    async def _check_build(self, session: AsyncSession, user: base_models.APIUser, build_id: ULID) -> None:
        """Check that the image build exists and the user has access to it."""
        stmt = select(session_schemas.BuildORM).where(session_schemas.BuildORM.id == build_id)
        res = await session.scalars(stmt)
        build_orm = res.one_or_none()
        authorized = (
            await self._check_environment(
                session=session, user=user, environment=build_orm.environment, scope=Scope.READ
            )
            if build_orm is not None
            else False
        )

        # If the output image is private, check that the user can read the source repository
        if build_orm is None or build_orm.result_image is None:
            authorized = False
        else:
            if self.builds_config.private_builds_enabled and build_orm.result_image.startswith(
                self.builds_config.build_output_private_image_prefix
            ):
                if build_orm.result_repository_url is None:
                    authorized = False
                else:
                    repo_data = await self.git_repositories_repo.get_repository(
                        repository_url=build_orm.result_repository_url,
                        user=user,
                        etag=None,
                    )
                    if (
                        not isinstance(repo_data.metadata, repo_models.Metadata)
                        or not repo_data.metadata.pull_permission
                    ):
                        authorized = False

        if not authorized or build_orm is None:
            raise errors.MissingResourceError(
                message=f"Build with id '{build_id}' does not exist or you do not have access to it."
            )

    async def _check_environment(
        self,
        session: AsyncSession,
        user: base_models.APIUser,
        environment: session_schemas.EnvironmentORM,
        scope: Scope,
    ) -> bool:
        """Checks whether the provided user has a specific permission on a session environment."""
        if environment.environment_kind == session_models.EnvironmentKind.GLOBAL:
            return scope == Scope.READ or user.is_admin

        launcher = await session.scalar(
            select(schemas.SessionLauncherORM).where(schemas.SessionLauncherORM.environment_id == environment.id)
        )
        authorized = False
        if launcher:
            authorized = await self.authz.has_permission(user, ResourceType.project, launcher.project_id, scope)
        return authorized

    async def _get_logs_per_container(self, session: AsyncSession, build_id: ULID) -> Sequence[models.ContainerLogs]:
        """Get the logs of a specific image build, organized by container."""
        # TODO: handle pagination?
        stmt = (
            select(schemas.ImageBuildLogORM)
            .where(schemas.ImageBuildLogORM.build_id == build_id)
            .order_by(schemas.ImageBuildLogORM.id.asc())
        )
        res = await session.stream_scalars(stmt)
        # Sort logs by container name, forcing "step-build-and-push" to be the first item (main container)
        return await _sort_logs_per_container(res, main_container=BUILD_MAIN_CONTAINER)


class ImageBuildPersistedLogsWriteRepository:
    """Repository for writing persisted logs of image builds.

    The write side is performed as a background task and does not access authz.
    """

    async def get_latest_log_timestamp(self, session: AsyncSession) -> int | None:
        """Returns the latest log timestamp."""
        stmt = (
            select(schemas.ImageBuildLogORM.timestamp)
            .select_from(schemas.ImageBuildLogORM)
            .order_by(schemas.ImageBuildLogORM.timestamp.desc())
            .limit(1)
        )
        res = await session.scalars(stmt)
        timestamp = res.one_or_none()
        return timestamp

    async def insert_build_logs(
        self, session: AsyncSession, logs_stream: AsyncIterator[models.UnsavedBuildLogLine]
    ) -> models.LogStreamMetadata:
        """Insert sessions logs into the persisted logs database."""
        log_count = 0
        last_timestamp = 0
        async for log in logs_stream:
            log_count += 1
            if log.timestamp > last_timestamp:
                last_timestamp = log.timestamp

            existing_log_res = await session.scalars(
                select(schemas.ImageBuildLogORM.id).where(schemas.ImageBuildLogORM.id == log.id)
            )
            existing_log_orm = existing_log_res.one_or_none()
            if existing_log_orm:
                continue

            log_orm = schemas.ImageBuildLogORM(
                id=log.id,
                build_id=log.build_id,
                container=log.container,
                timestamp=log.timestamp,
                log_line=log.log_line,
            )
            session.add(log_orm)
            await session.flush()
        return models.LogStreamMetadata(log_count=log_count, last_timestamp=last_timestamp)

    async def delete_expired_build_logs(self, session: AsyncSession, before: datetime) -> int:
        """Remove expired build logs from the database."""
        nano_ts = models.NanoTimestamp.from_datetime(before)
        delete_logs_stmt = delete(schemas.ImageBuildLogORM).where(schemas.ImageBuildLogORM.timestamp < nano_ts)
        res = await session.execute(delete_logs_stmt)
        deleted_logs_count = res.rowcount
        return deleted_logs_count


async def _sort_logs_per_container(
    result: AsyncScalarResult[schemas.AmaltheaSessionLogORM] | AsyncScalarResult[schemas.ImageBuildLogORM],
    main_container: str | None = None,
) -> Sequence[models.ContainerLogs]:
    """Organize logs per container."""
    logs_per_container: dict[str, list[models.LogLine]] = dict()
    async for log_entry in result:
        container = log_entry.container
        logs = logs_per_container.get(container)
        if logs is None:
            logs = list[models.LogLine]()
            logs_per_container[container] = logs
        logs.append(models.LogLine(timestamp=log_entry.timestamp, log_line=log_entry.log_line))
    # Sort containers by name, forcing `main_container` to be the first item
    containers_set = set(logs_per_container.keys())
    containers: list[str] = list()
    if main_container and main_container in containers_set:
        containers.append(main_container)
        containers_set.remove(main_container)
    containers.extend(sorted(containers_set))
    return [models.ContainerLogs(container=container, logs=logs_per_container[container]) for container in containers]
