"""Adapters for session runners database classes."""

from __future__ import annotations

import base64
import random
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from ulid import ULID

from renku_data_services import base_models, errors
from renku_data_services.authz.authz import Authz
from renku_data_services.authz.models import Scope
from renku_data_services.base_models.core import ResourceType
from renku_data_services.session_runners import models
from renku_data_services.session_runners import orm as schemas


class SessionRunnersRepository:
    """Repository for reading persisted logs of Amalthea sessions."""

    def __init__(self, authz: Authz) -> None:
        self.authz: Authz = authz

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
        user_orm.dump()
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
        # TODO: handle sessions assigned to the runner
        await session.flush()
        return runner_orm.dump()

    @staticmethod
    def _generate_registration_token(size: int = 18) -> str:
        """Returns a random code to use as a registration token."""
        rand = random.SystemRandom()
        return base64.urlsafe_b64encode(rand.randbytes(size)).decode()
