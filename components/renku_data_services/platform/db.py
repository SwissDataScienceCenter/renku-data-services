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

    async def get_config(self) -> models.PlatformConfig:
        """Get the platform configuration from the database."""
        async with self.session_maker() as session:
            config = await session.scalar(select(schemas.PlatformConfigORM))
            if config is None:
                raise errors.MissingResourceError(
                    message="The platform configuration has not been initialized yet", quiet=True
                )
            return config.dump()

    async def create_initial_config(self, user: base_models.APIUser) -> models.PlatformConfig:
        """Create the initial platform configuration in the database."""
        if user.id is None or not user.is_admin:
            raise errors.Unauthorized(
                message="You do not have the required permissions for this operation.", quiet=True
            )

        async with self.session_maker() as session, session.begin():
            result = await session.scalars(select(schemas.PlatformConfigORM))
            existing_config = result.one_or_none()
            if existing_config is not None:
                return existing_config.dump()
            config = schemas.PlatformConfigORM(id=models.ConfigID.config)
            session.add(config)
            await session.flush()
            await session.refresh(config)
            return config.dump()

    async def update_config(self, user: base_models.APIUser, etag: str, **kwargs: dict) -> models.PlatformConfig:
        """Update the platform configuration."""
        if user.id is None or not user.is_admin:
            raise errors.Unauthorized(
                message="You do not have the required permissions for this operation.", quiet=True
            )

        async with self.session_maker() as session, session.begin():
            result = await session.scalars(select(schemas.PlatformConfigORM))
            config = result.one_or_none()
            if config is None:
                raise errors.MissingResourceError(message="The platform configuration has not been initialized yet")

            current_etag = config.dump().etag
            if current_etag != etag:
                raise errors.ConflictError(message=f"Current ETag is {current_etag}, not {etag}.")

            for key, value in kwargs.items():
                if key in ["incident_banner"]:
                    setattr(config, key, value)

            await session.flush()
            await session.refresh(config)

            return config.dump()
