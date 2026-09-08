"""Adapters for session runners database classes."""

from __future__ import annotations

import base64
import random

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
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

    async def get_runner(self, session: AsyncSession, user: base_models.APIUser, id: ULID) -> models.SessionRunner:
        """Get a session runner from the database."""
        if not user.is_authenticated or not user.id:
            raise errors.UnauthorizedError(message="You have to be authenticated to perform this operation.")
        stmt = select(schemas.SessionRunnerORM).where(schemas.SessionRunnerORM.id == id)
        if not user.is_admin:
            stmt = stmt.where(schemas.SessionRunnerORM.user_id == user.id)
        res = await session.scalars(stmt)
        runner_orm = res.one_or_none()
        if runner_orm is None:
            raise errors.MissingResourceError(
                message=f"Session runner with id '{id}' does not exist or you do not have access to it."
            )
        return runner_orm.dump()

    async def insert_runner(
        self, session: AsyncSession, user: base_models.APIUser, runner: models.UnsavedSessionRunner
    ) -> models.SessionRunner:
        """Insert a new session runner into the database."""
        if not user.is_authenticated or not user.id:
            raise errors.UnauthorizedError(message="You have to be authenticated to perform this operation.")
        authorized = await self.authz.has_permission(
            user=user, resource_type=ResourceType.resource_pool, resource_id=runner.resource_pool_id, scope=Scope.READ
        )
        if not authorized:
            raise errors.MissingResourceError(
                message=f"Resource pool id '{runner.resource_pool_id}' does not exist or you do not have access to it."
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

    @staticmethod
    def _generate_registration_token(size: int = 16) -> str:
        """Returns a random code to use as a registration token."""
        rand = random.SystemRandom()
        return base64.b64encode(rand.randbytes(size)).decode()
