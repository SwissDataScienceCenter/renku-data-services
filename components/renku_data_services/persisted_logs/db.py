"""Adapters for persisted logs database classes."""

from collections.abc import AsyncIterator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from renku_data_services import base_models, errors
from renku_data_services.app_config import logging
from renku_data_services.authz.authz import Authz, ResourceType
from renku_data_services.authz.models import Scope
from renku_data_services.persisted_logs import models
from renku_data_services.persisted_logs import orm as schemas
from renku_data_services.persisted_logs.constants import BUILD_MAIN_CONTAINER, SESSION_MAIN_CONTAINER
from renku_data_services.session import models as session_models
from renku_data_services.session import orm as session_schemas

logger = logging.getLogger(__name__)


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


class ImageBuildPersistedLogsReadRepository:
    """Repository for persisted logs of image builds."""

    def __init__(self, authz: Authz) -> None:
        self.authz: Authz = authz

    async def get_build_logs(
        self, session: AsyncSession, user: base_models.APIUser, build_id: ULID
    ) -> models.SessionRunLogs:
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

    async def _get_logs_per_container(self, session: AsyncSession, build_id: ULID) -> models.SessionRunLogs:
        """Get the logs of a specific image build, organized by container."""
        # TODO: handle pagination?
        stmt = (
            select(schemas.ImageBuildLogsORM)
            .where(schemas.ImageBuildLogsORM.build_id == build_id)
            .order_by(schemas.ImageBuildLogsORM.id.asc())
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
        # Sort container by name, forcing "step-build-and-push" to be the first item (main container)
        containers_set = set(logs_per_container.keys())
        containers: list[str] = list()
        if BUILD_MAIN_CONTAINER in containers_set:
            containers.append(BUILD_MAIN_CONTAINER)
            containers_set.remove(BUILD_MAIN_CONTAINER)
        containers.extend(sorted(containers_set))
        result: dict[str, list[models.LogLine]] = dict()
        for container in containers:
            result[container] = logs_per_container[container]
        return result
