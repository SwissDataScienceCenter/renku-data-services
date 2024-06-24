"""Adapters for platform config database classes."""

from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from renku_data_services import base_models, errors
from renku_data_services.platform import apispec, models
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
                raise errors.MissingResourceError(
                    message="The platform configuration has not been initialized yet", quiet=True
                )
            return config.dump()

    async def insert_config(
        self,
        user: base_models.APIUser,
        new_config: apispec.PlatformConfigPost,
    ) -> models.PlatformConfig:
        """Create the initial platform configuration."""
        if user.id is None or not user.is_admin:
            raise errors.Unauthorized(
                message="You do not have the required permissions for this operation.", quiet=True
            )

        config = schemas.PlatformConfigORM(id=models.ConfigID.config)
        if new_config.disable_ui is not None:
            config.disable_ui = new_config.disable_ui
        if new_config.maintenance_banner is not None:
            config.maintenance_banner = new_config.maintenance_banner
        if new_config.status_page_id is not None:
            config.status_page_id = new_config.status_page_id

        async with self.session_maker() as session, session.begin():
            result = await session.scalars(select(schemas.PlatformConfigORM))
            existing_config = result.one_or_none()
            if existing_config is not None:
                raise errors.ConflictError(message="The platform configuration already exists")
            session.add(config)
            await session.flush()
            await session.refresh(config)
            return config.dump()
