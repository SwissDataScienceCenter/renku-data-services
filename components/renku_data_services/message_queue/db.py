"""Adapters for project database classes."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from renku_data_services import errors
from renku_data_services.app_config import logging
from renku_data_services.message_queue import orm as schemas
from renku_data_services.message_queue.models import Reprovisioning

logger = logging.getLogger(__name__)


class ReprovisioningRepository:
    """Repository for Reprovisioning."""

    def __init__(self, session_maker: Callable[..., AsyncSession]) -> None:
        self.session_maker = session_maker

    async def start(self) -> Reprovisioning:
        """Create a new reprovisioning."""
        async with self.session_maker() as session, session.begin():
            active_reprovisioning = await session.scalar(select(schemas.ReprovisioningORM))
            if active_reprovisioning:
                raise errors.ConflictError(message="A reprovisioning is already in progress")

            reprovisioning_orm = schemas.ReprovisioningORM(start_date=datetime.now(UTC).replace(microsecond=0))
            session.add(reprovisioning_orm)

            return reprovisioning_orm.dump()

    async def get_active_reprovisioning(self) -> Reprovisioning | None:
        """Get current reprovisioning."""
        async with self.session_maker() as session:
            active_reprovisioning = await session.scalar(select(schemas.ReprovisioningORM))
            return active_reprovisioning.dump() if active_reprovisioning else None

    async def stop(self) -> None:
        """Stop current reprovisioning."""
        async with self.session_maker() as session, session.begin():
            await session.execute(delete(schemas.ReprovisioningORM))
