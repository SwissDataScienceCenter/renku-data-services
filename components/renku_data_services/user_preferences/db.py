"""Adapters for user preferences database classes."""
from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.user_preferences import models
from renku_data_services.user_preferences import orm as schemas


class _Base:
    """Base class for repositories."""

    def __init__(self, sync_sqlalchemy_url: str, async_sqlalchemy_url: str, debug: bool = False):
        self.engine = create_async_engine(async_sqlalchemy_url, echo=debug)
        self.sync_engine = create_engine(sync_sqlalchemy_url, echo=debug)
        self.session_maker = sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )  # type: ignore[call-overload]


class UserPreferencesRepository(_Base):
    """Repository for user preferences."""

    def __init__(
        self,
        sync_sqlalchemy_url: str,
        async_sqlalchemy_url: str,
        debug: bool = False,
    ):
        super().__init__(sync_sqlalchemy_url, async_sqlalchemy_url, debug)

    async def get_user_preferences(
        self,
        user: base_models.APIUser,
    ) -> models.UserPreferences | None:
        """Get user preferences from the database."""
        async with self.session_maker() as session:
            if not user.is_authenticated:
                raise errors.Unauthorized(message="Anonymous users cannot have user preferences.")

            res = await session.execute(
                select(schemas.UserPreferencesORM).where(schemas.UserPreferencesORM.user_id == user.id)
            )
            user_preferences = res.one_or_none()

            if user_preferences is None:
                return None
            return user_preferences[0].dump()
