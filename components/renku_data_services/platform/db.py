"""Adapters for platform config database classes."""

from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from renku_data_services import errors
from renku_data_services.platform import models
from renku_data_services.platform import orm as schemas


class PlatformRepository:
    """Repository for the platform config."""

    def __init__(
        self,
        session_maker: Callable[..., AsyncSession],
    ):
        self.session_maker = session_maker

    async def get_config(self) -> models.PlatformConfig:
        """Get the platform configuration from the database."""
        async with self.session_maker() as session:
            config = await session.scalar(select(schemas.PlatformConfigORM))
            if config is None:
                raise errors.MissingResourceError(message="The platform configuration has not been initialized yet")
            return config.dump()
