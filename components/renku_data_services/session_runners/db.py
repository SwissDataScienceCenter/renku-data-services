"""Adapters for session runners database classes."""

from __future__ import annotations

import base64
import random
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncScalarResult, AsyncSession
from sqlalchemy.orm import selectinload
from ulid import ULID

from renku_data_services import base_models, errors
from renku_data_services.authz.authz import Authz
from renku_data_services.authz.models import Scope
from renku_data_services.base_models.core import ResourceType
from renku_data_services.crc import models as crc_models
from renku_data_services.crc import orm as crc_schemas
from renku_data_services.session_runners import models
from renku_data_services.session_runners import orm as schemas


class UserSessionRunnersRepository:
    """Repository for user-scoped session runners.

    This repository exposes database operations to be done on behalf of authenticated users.
    """

    def __init__(
        self,
        authz: Authz,
        encryption_key: bytes,
        session_maker: Callable[..., AsyncSession],
    ) -> None:
        self.authz: Authz = authz
        self._encryption_key = encryption_key
        self.session_maker = session_maker

    async def get_all_runners(
        self, session: AsyncSession, user: base_models.APIUser, all_users: bool = False
    ) -> AsyncIterator[models.UserSessionRunner]:
        """Get all user-scoped session runners for a user from the database.

        If `all_users` is True, then all session runners are returned provided that the
        authenticated user is an admin.
        """
        stream = await self._get_all_runners_orm(session=session, user=user, all_users=all_users)
        async for runner_orm in stream:
            yield runner_orm.dump()

    async def _get_all_runners_orm(
        self, session: AsyncSession, user: base_models.APIUser, all_users: bool
    ) -> AsyncScalarResult[schemas.UserSessionRunnerORM]:
        if not user.is_authenticated or not user.id:
            raise errors.UnauthorizedError(message="You have to be authenticated to perform this operation.")
        stmt = select(schemas.UserSessionRunnerORM).order_by(schemas.UserSessionRunnerORM.id.desc())
        if not user.is_admin or not all_users:
            stmt = stmt.where(schemas.UserSessionRunnerORM.user_id == user.id)
        return await session.stream_scalars(stmt)

    async def get_runner_or_none(
        self, session: AsyncSession, user: base_models.APIUser, runner_id: ULID
    ) -> models.UserSessionRunner | None:
        """Get a user-scoped session runner from the database."""
        runner_orm = await self._get_runner_or_none_orm(session=session, user=user, runner_id=runner_id)
        if runner_orm is None:
            return None
        return runner_orm.dump()

    async def get_runner(
        self, session: AsyncSession, user: base_models.APIUser, runner_id: ULID
    ) -> models.UserSessionRunner:
        """Get a user-scoped session runner from the database."""
        runner = await self.get_runner_or_none(session=session, user=user, runner_id=runner_id)
        if runner is None:
            raise errors.MissingResourceError(
                message=f"Session runner with id '{runner_id}' does not exist or you do not have access to it."
            )
        return runner

    async def _get_runner_or_none_orm(
        self, session: AsyncSession, user: base_models.APIUser, runner_id: ULID
    ) -> schemas.UserSessionRunnerORM | None:
        if not user.is_authenticated or not user.id:
            raise errors.UnauthorizedError(message="You have to be authenticated to perform this operation.")
        stmt = select(schemas.UserSessionRunnerORM).where(schemas.UserSessionRunnerORM.id == runner_id)
        if not user.is_admin:
            stmt = stmt.where(schemas.UserSessionRunnerORM.user_id == user.id)
        res = await session.scalars(stmt)
        return res.one_or_none()

    async def insert_runner(
        self, session: AsyncSession, user: base_models.APIUser, runner: models.UnsavedUserSessionRunner
    ) -> models.UserSessionRunner:
        """Insert a new user-scoped session runner into the database."""
        if not user.is_authenticated or not user.id:
            raise errors.UnauthorizedError(message="You have to be authenticated to perform this operation.")
        authorized = (
            await self.authz.has_permission(
                user=user,
                resource_type=ResourceType.resource_pool,
                resource_id=runner.resource_pool_id,
                scope=Scope.READ,
            )
            if runner.resource_pool_id > 0
            else False
        )
        if not authorized:
            raise errors.MissingResourceError(
                message=f"Resource pool with id '{runner.resource_pool_id}' "
                "does not exist or you do not have access to it."
            )
        compatible = False
        rp_stmt = select(crc_schemas.ResourcePoolORM).where(crc_schemas.ResourcePoolORM.id == runner.resource_pool_id)
        rp_res = await session.scalars(rp_stmt)
        rp_orm = rp_res.one_or_none()
        if (
            rp_orm
            and rp_orm.remote_json
            and rp_orm.remote_json.get("kind") == crc_models.RemoteConfigurationKind.user_runners.value
        ):
            compatible = True
        if not compatible:
            raise errors.ValidationError(
                message=f"Resource pool with id '{runner.resource_pool_id}' " "does not accept session runners."
            )
        registration_token = self._generate_registration_token()
        runner_orm = schemas.UserSessionRunnerORM(
            user_id=user.id,
            resource_pool_id=runner.resource_pool_id,
            registration_token=registration_token,
            status=models.RunnerStatus.never_contacted,
        )
        session.add(runner_orm)
        await session.flush()
        return runner_orm.dump(include_registration_token=True)

    async def register_runner(
        self, session: AsyncSession, registration_token: str
    ) -> tuple[models.UserSessionRunner, base_models.AuthenticatedAPIUser]:
        """Register a new user-scoped session runner and update it in the database.

        Returns the corresponding session runner and its owner so that authentication tokens can be minted.
        """
        stmt = (
            select(schemas.UserSessionRunnerORM)
            .where(schemas.UserSessionRunnerORM.registration_token == registration_token)
            .options(selectinload(schemas.UserSessionRunnerORM.user))
        )
        res = await session.scalars(stmt)
        runner_orm = res.one_or_none()
        if runner_orm is None:
            raise errors.MissingResourceError(
                message=f"Session runner with registration token '{registration_token}' "
                "does not exist or you do not have access to it."
            )
        user_orm = runner_orm.user
        user = base_models.AuthenticatedAPIUser(
            is_admin=False,
            id=user_orm.keycloak_id,
            access_token="",  # nosec B106
            first_name=user_orm.first_name,
            last_name=user_orm.last_name,
            email=user_orm.email or "",
            access_token_expires_at=None,
            roles=[],
        )
        runner_orm.status = models.RunnerStatus.initializing
        runner_orm.last_contact = datetime.now(tz=UTC)
        await session.flush()
        return runner_orm.dump(), user

    async def update_runner(
        self, session: AsyncSession, user: base_models.APIUser, runner_id: ULID, patch: models.UserSessionRunnerPatch
    ) -> models.UserSessionRunner:
        """Update a user-scoped session runner.

        The runner's registration token is removed during this operation.
        This prevents accidentally running the same runner on two different machines.
        """
        runner_orm = await self._get_runner_or_none_orm(session=session, user=user, runner_id=runner_id)
        if runner_orm is None:
            raise errors.MissingResourceError(
                message=f"Session runner with id '{id}' does not exist or you do not have access to it."
            )
        runner_orm.status = patch.status
        runner_orm.last_contact = datetime.now(tz=UTC)
        runner_orm.registration_token = None
        await session.flush()
        return runner_orm.dump()

    async def delete_runner(self, session: AsyncSession, user: base_models.APIUser, runner_id: ULID) -> None:
        """Remove a user-scoped session runner from the database."""
        runner_orm = await self._get_runner_or_none_orm(session=session, user=user, runner_id=runner_id)
        if runner_orm is None:
            return None
        await session.delete(runner_orm)
        await session.flush()
        return None

    async def insert_remote_session(
        self,
        user: base_models.APIUser,
        renku_session: models.UnsavedRemoteUserSession,
        session: AsyncSession | None = None,
    ) -> models.RemoteUserSession:
        """Insert a new remote Renku session into the database.

        Note: will wrap into a database transaction if no DB session is passed.
        """
        if session is None:
            async with self.session_maker() as db_session, db_session.begin():
                return await self._insert_remote_session_inner(
                    session=db_session, user=user, renku_session=renku_session
                )
        return await self._insert_remote_session_inner(session=session, user=user, renku_session=renku_session)

    async def _insert_remote_session_inner(
        self, session: AsyncSession, user: base_models.APIUser, renku_session: models.UnsavedRemoteUserSession
    ) -> models.RemoteUserSession:
        if not user.is_authenticated or not user.id:
            raise errors.UnauthorizedError(message="You have to be authenticated to perform this operation.")

        await self._check_eventually_schedulable(session=session, user_id=user.id, renku_session=renku_session)

        # Handle existing entry in the database
        stmt = select(schemas.RemoteUserSessionORM).where(schemas.RemoteUserSessionORM.id == renku_session.session_id)
        res = await session.scalars(stmt)
        session_orm = res.one_or_none()
        if session_orm:
            await session.delete(session_orm)
            await session.flush()

        session_orm = schemas.RemoteUserSessionORM(
            id=renku_session.session_id,
            user_id=user.id,
            resource_pool_id=renku_session.resource_pool_id,
            runner_id=None,
        )
        session.add(session_orm)
        await session.flush()
        return session_orm.dump()

    async def _check_eventually_schedulable(
        self, session: AsyncSession, user_id: str, renku_session: models.UnsavedRemoteUserSession
    ) -> None:
        """Check that a new remote Renku session is eventually schedulable.

        This check will reject cases where there are no runners registered
        with the resource pool picked for the session.
        """
        stmt = (
            select(schemas.UserSessionRunnerORM)
            .where(schemas.UserSessionRunnerORM.user_id == user_id)
            .where(schemas.UserSessionRunnerORM.resource_pool_id == renku_session.resource_pool_id)
            .where(schemas.UserSessionRunnerORM.status.in_([models.RunnerStatus.ready, models.RunnerStatus.not_ready]))
            .limit(1)
        )
        res = await session.scalars(stmt)
        runner_orm = res.first()
        if runner_orm is None:
            raise errors.ValidationError(
                message="You do not have any registered session runner "
                f"for the resource pool with ID {renku_session.resource_pool_id}."
            )

    @staticmethod
    def _generate_registration_token(size: int = 18) -> str:
        """Returns a random code to use as a registration token."""
        rand = random.SystemRandom()
        return base64.urlsafe_b64encode(rand.randbytes(size)).decode()


class UserSessionRunnersSchedulingRepository:
    """Repository for scheduling sessions onto user-scoped runners.

    This repository exposes database operations to be done by a service account,
    i.e. calls are not authenticated.
    """

    async def get_all_remote_sessions(self, session: AsyncSession) -> AsyncIterator[models.RemoteUserSession]:
        """Get all remote Renku sessions from the database."""
        stmt = select(schemas.RemoteUserSessionORM).order_by(schemas.RemoteUserSessionORM.id.asc())
        res = await session.stream_scalars(stmt)
        async for session_orm in res:
            yield session_orm.dump()

    async def get_all_runners(
        self, session: AsyncSession, filter_status: models.RunnerStatus | None = None
    ) -> AsyncIterator[models.UserSessionRunner]:
        """Get all user-scoped session runners from the database."""
        stmt = select(schemas.UserSessionRunnerORM)
        if filter_status is not None:
            stmt = stmt.where(schemas.UserSessionRunnerORM.status == filter_status)
        res = await session.stream_scalars(stmt)
        async for runner_orm in res:
            yield runner_orm.dump()

    async def get_viable_runners(
        self, session: AsyncSession, renku_session_id: str
    ) -> AsyncIterator[models.UserSessionRunner]:
        """Get all user-scoped session runners which can run a given remote Renku session."""
        stmt_session = select(schemas.RemoteUserSessionORM).where(schemas.RemoteUserSessionORM.id == renku_session_id)
        res_session = await session.scalars(stmt_session)
        session_orm = res_session.one_or_none()
        if session_orm is None:
            return
        stmt_runners = (
            select(schemas.UserSessionRunnerORM)
            .where(schemas.UserSessionRunnerORM.user_id == session_orm.user_id)
            .where(schemas.UserSessionRunnerORM.resource_pool_id == session_orm.resource_pool_id)
            .where(schemas.UserSessionRunnerORM.status == models.RunnerStatus.ready)
            .order_by(schemas.UserSessionRunnerORM.id.desc())
        )
        res_runners = await session.stream_scalars(stmt_runners)
        async for runner_orm in res_runners:
            yield runner_orm.dump()

    async def update_remote_session_set_runner(
        self, session: AsyncSession, renku_session_id: str, runner_id: ULID
    ) -> models.RemoteUserSession:
        """Update a remote Renku session by setting its runner."""
        session_orm = await self._get_remote_session_orm_or_none(session=session, renku_session_id=renku_session_id)
        if session_orm is None:
            raise errors.ValidationError(message=f"The Renku session {renku_session_id} does not exist.")
        session_orm.runner_id = runner_id
        await session.flush()
        return session_orm.dump()

    async def delete_remote_session(self, session: AsyncSession, renku_session_id: str) -> None:
        """Remove a remote Renku session from the database."""
        session_orm = await self._get_remote_session_orm_or_none(session=session, renku_session_id=renku_session_id)
        if session_orm is None:
            return None
        await session.delete(session_orm)
        return None

    async def _get_remote_session_orm_or_none(
        self, session: AsyncSession, renku_session_id: str
    ) -> schemas.RemoteUserSessionORM | None:
        stmt = select(schemas.RemoteUserSessionORM).where(schemas.RemoteUserSessionORM.id == renku_session_id)
        res = await session.scalars(stmt)
        return res.one_or_none()

    async def update_runner_status(
        self, session: AsyncSession, runner_id: ULID, status: models.RunnerStatus
    ) -> models.UserSessionRunner:
        """Update the status of a user-scoped session runner."""
        stmt = select(schemas.UserSessionRunnerORM).where(schemas.UserSessionRunnerORM.id == runner_id)
        res = await session.scalars(stmt)
        runner_orm = res.one_or_none()
        if runner_orm is None:
            raise errors.MissingResourceError(message=f"Session runner with id '{runner_id}' does not exist.")
        runner_orm.status = status
        await session.flush()
        return runner_orm.dump()
