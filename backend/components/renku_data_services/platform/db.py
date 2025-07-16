"""Adapters for platform config database classes."""

from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from renku_data_services import base_models, errors
from renku_data_services.platform import models
from renku_data_services.platform import orm as schemas


class PlatformRepository:
    """Repository for the platform config."""

    def __init__(
        self,
        session_maker: Callable[..., AsyncSession],
    ):
        self.session_maker = session_maker

    async def get_or_create_config(self) -> models.PlatformConfig:
        """Get the platform configuration from the database or create it if it does not exist yet."""
        async with self.session_maker() as session, session.begin():
            config = await session.scalar(select(schemas.PlatformConfigORM))
            if config is None:
                config = schemas.PlatformConfigORM(id=models.ConfigID.config)
                session.add(config)
                await session.flush()
                await session.refresh(config)
            return config.dump()

    async def update_config(
        self, user: base_models.APIUser, etag: str, patch: models.PlatformConfigPatch
    ) -> models.PlatformConfig:
        """Update the platform configuration."""
        if user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")
        if not user.is_admin:
            raise errors.ForbiddenError(message="You do not have the required permissions for this operation.")

        async with self.session_maker() as session, session.begin():
            result = await session.scalars(select(schemas.PlatformConfigORM))
            config = result.one_or_none()
            if config is None:
                raise errors.MissingResourceError(message="The platform configuration has not been initialized yet")

            current_etag = config.dump().etag
            if current_etag != etag:
                raise errors.ConflictError(message=f"Current ETag is {current_etag}, not {etag}.")

            if patch.incident_banner is not None:
                config.incident_banner = patch.incident_banner

            await session.flush()
            await session.refresh(config)

            return config.dump()
