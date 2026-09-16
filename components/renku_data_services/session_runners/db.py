"""Adapters for session runners database classes."""

from __future__ import annotations

import base64
import random
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
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


class SessionRunnersRepository:
    """Repository for session runners."""

    def __init__(self, authz: Authz) -> None:
        self.authz: Authz = authz

    async def get_all_runners(
        self, session: AsyncSession, user: base_models.APIUser
    ) -> AsyncIterator[models.SessionRunner]:
        """Get all session runners for a user from the database."""
        if not user.is_authenticated or not user.id:
            raise errors.UnauthorizedError(message="You have to be authenticated to perform this operation.")
        # TODO: handle admin users -> can see all runners
        stmt = (
            select(schemas.SessionRunnerORM)
            .where(schemas.SessionRunnerORM.user_id == user.id)
            .order_by(schemas.SessionRunnerORM.id.desc())
        )
        res = await session.stream_scalars(stmt)
        async for runner_orm in res:
            yield runner_orm.dump()

    async def get_runner_or_none(
        self, session: AsyncSession, user: base_models.APIUser, id: ULID
    ) -> models.SessionRunner | None:
        """Get a session runner from the database."""
        if not user.is_authenticated or not user.id:
            raise errors.UnauthorizedError(message="You have to be authenticated to perform this operation.")
        stmt = select(schemas.SessionRunnerORM).where(schemas.SessionRunnerORM.id == id)
        if not user.is_admin:
            stmt = stmt.where(schemas.SessionRunnerORM.user_id == user.id)
        res = await session.scalars(stmt)
        runner_orm = res.one_or_none()
        if runner_orm is None:
            return None
        return runner_orm.dump()

    async def get_runner(self, session: AsyncSession, user: base_models.APIUser, id: ULID) -> models.SessionRunner:
        """Get a session runner from the database."""
        runner = await self.get_runner_or_none(session=session, user=user, id=id)
        if runner is None:
            raise errors.MissingResourceError(
                message=f"Session runner with id '{id}' does not exist or you do not have access to it."
            )
        return runner

    async def insert_runner(
        self, session: AsyncSession, user: base_models.APIUser, runner: models.UnsavedSessionRunner
    ) -> models.SessionRunner:
        """Insert a new session runner into the database."""
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
            and rp_orm.remote_json.get("kind") == crc_models.RemoteConfigurationKind.runners.value
        ):
            compatible = True
        if not compatible:
            raise errors.ValidationError(
                message=f"Resource pool with id '{runner.resource_pool_id}' " "does not accept session runners."
            )
        registration_token = self._generate_registration_token()
        runner_orm = schemas.SessionRunnerORM(
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
    ) -> tuple[models.SessionRunner, base_models.AuthenticatedAPIUser]:
        """Register a new session runner and update it in the database."""
        stmt = (
            select(schemas.SessionRunnerORM)
            .where(schemas.SessionRunnerORM.registration_token == registration_token)
            .options(selectinload(schemas.SessionRunnerORM.user))
        )
        res = await session.scalars(stmt)
        runner_orm = res.one_or_none()
        if runner_orm is None:
            raise errors.MissingResourceError(
                message=f"Session runner with registration token '{registration_token}' "
                "does not exist or you do not have access to it."
            )
        user_orm = runner_orm.user
        user_orm.dump()  # TODO
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

    async def update_runner_from_contact(
        self,
        session: AsyncSession,
        user: base_models.APIUser,
        session_runner_id: ULID,
        payload: models.SessionRunnerContactPayload,
    ) -> models.SessionRunner:
        """Update a session runner based on the contact payload it sent."""
        if not user.is_authenticated or not user.id:
            raise errors.UnauthorizedError(message="You have to be authenticated to perform this operation.")
        stmt = select(schemas.SessionRunnerORM).where(schemas.SessionRunnerORM.id == session_runner_id)
        if not user.is_admin:
            stmt = stmt.where(schemas.SessionRunnerORM.user_id == user.id)
        res = await session.scalars(stmt)
        runner_orm = res.one_or_none()
        if runner_orm is None:
            raise errors.MissingResourceError(
                message=f"Session runner with id '{id}' does not exist or you do not have access to it."
            )
        runner_orm.status = payload.status
        runner_orm.last_contact = datetime.now(tz=UTC)
        runner_orm.registration_token = None
        # TODO: handle sessions assigned to the runner
        await session.flush()
        return runner_orm.dump()

    async def delete_runner(self, session: AsyncSession, user: base_models.APIUser, runner_id: ULID) -> None:
        """Remove a session runner from the database."""
        if not user.is_authenticated or not user.id:
            raise errors.UnauthorizedError(message="You have to be authenticated to perform this operation.")
        stmt = select(schemas.SessionRunnerORM).where(schemas.SessionRunnerORM.id == runner_id)
        if not user.is_admin:
            stmt = stmt.where(schemas.SessionRunnerORM.user_id == user.id)
        res = await session.scalars(stmt)
        runner_orm = res.one_or_none()
        if runner_orm is None:
            return None
        await session.delete(runner_orm)
        return None

    @staticmethod
    def _generate_registration_token(size: int = 18) -> str:
        """Returns a random code to use as a registration token."""
        rand = random.SystemRandom()
        return base64.urlsafe_b64encode(rand.randbytes(size)).decode()


class SessionRunnersSchedulingRepository:
    """Repository for scheduling sessions onto runners."""

    def __init__(
        self,
        session_maker: Callable[..., AsyncSession],
    ) -> None:
        self.session_maker = session_maker

    async def insert_assigned_session(
        self,
        user: base_models.APIUser,
        renku_session: models.UnsavedAssignedSession,
        session: AsyncSession | None = None,
    ) -> models.AssignedSession:
        """Insert a new assigned session into the database.

        Note: will wrap into a database transaction if no DB session is passed.
        """
        if session is None:
            async with self.session_maker() as db_session, db_session.begin():
                return await self._insert_assigned_session_inner(
                    session=db_session, user=user, renku_session=renku_session
                )
        return await self._insert_assigned_session_inner(session=session, user=user, renku_session=renku_session)

    async def _insert_assigned_session_inner(
        self, session: AsyncSession, user: base_models.APIUser, renku_session: models.UnsavedAssignedSession
    ) -> models.AssignedSession:
        if not user.is_authenticated or not user.id:
            raise errors.UnauthorizedError(message="You have to be authenticated to perform this operation.")
        await self._check_eventually_schedulable(session=session, user_id=user.id, renku_session=renku_session)
        session_orm = schemas.AssignedSessionORM(
            id=renku_session.session_id,
            user_id=user.id,
            resource_pool_id=renku_session.resource_pool_id,
            runner_id=None,
        )
        session.add(session_orm)
        await session.flush()
        return session_orm.dump()

    async def _check_eventually_schedulable(
        self, session: AsyncSession, user_id: str, renku_session: models.UnsavedAssignedSession
    ) -> None:
        """Check that a new session is eventually schedulable.

        This check will reject cases where there are no runners registered
        with the resource pool picked for the session.
        """
        stmt = (
            select(schemas.SessionRunnerORM)
            .where(schemas.SessionRunnerORM.user_id == user_id)
            .where(schemas.SessionRunnerORM.resource_pool_id == renku_session.resource_pool_id)
            .where(schemas.SessionRunnerORM.status.in_([models.RunnerStatus.ready, models.RunnerStatus.not_ready]))
            .limit(1)
        )
        res = await session.scalars(stmt)
        runner_orm = res.first()
        if runner_orm is None:
            raise errors.ValidationError(
                message="You do not have any registered session runner "
                f"for resource pool {renku_session.resource_pool_id}."
            )
