"""Adapters for user preferences database classes."""

from collections.abc import Callable
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.user_preferences import models
from renku_data_services.user_preferences import orm as schemas
from renku_data_services.user_preferences.config import UserPreferencesConfig


class _Base:
    """Base class for repositories."""

    def __init__(self, session_maker: Callable[..., AsyncSession]) -> None:
        self.session_maker = session_maker


class UserPreferencesRepository(_Base):
    """Repository for user preferences."""

    def __init__(
        self, user_preferences_config: UserPreferencesConfig, session_maker: Callable[..., AsyncSession]
    ) -> None:
        super().__init__(session_maker)
        self.user_preferences_config = user_preferences_config

    async def get_user_preferences(
        self,
        user: base_models.APIUser,
    ) -> models.UserPreferences:
        """Get user preferences from the database."""
        async with self.session_maker() as session:
            if not user.is_authenticated:
                raise errors.Unauthorized(message="Anonymous users cannot have user preferences.")

            res = await session.scalars(
                select(schemas.UserPreferencesORM).where(schemas.UserPreferencesORM.user_id == user.id)
            )
            user_preferences = res.one_or_none()

            if user_preferences is None:
                raise errors.MissingResourceError(message="Preferences not found for user.")
            return user_preferences.dump()

    async def delete_user_preferences(self, user: base_models.APIUser) -> None:
        """Delete user preferences from the database."""
        async with self.session_maker() as session, session.begin():
            if not user.is_authenticated:
                return

            res = await session.scalars(
                select(schemas.UserPreferencesORM).where(schemas.UserPreferencesORM.user_id == user.id)
            )
            user_preferences = res.one_or_none()

            if user_preferences is None:
                return

            await session.delete(user_preferences)

    async def add_pinned_project(self, user: base_models.APIUser, project_slug: str) -> models.UserPreferences:
        """Adds a new pinned project to the user's preferences."""
        async with self.session_maker() as session, session.begin():
            if not user.is_authenticated:
                raise errors.Unauthorized(message="Anonymous users cannot have user preferences.")

            res = await session.scalars(
                select(schemas.UserPreferencesORM).where(schemas.UserPreferencesORM.user_id == user.id)
            )
            user_preferences = res.one_or_none()

            if user_preferences is None:
                new_preferences = models.UserPreferences(
                    user_id=cast(str, user.id), pinned_projects=models.PinnedProjects(project_slugs=[project_slug])
                )
                user_preferences = schemas.UserPreferencesORM.load(new_preferences)
                session.add(user_preferences)
                return user_preferences.dump()

            project_slugs: list[str]
            project_slugs = user_preferences.pinned_projects.get("project_slugs", [])

            # Do nothing if the project is already listed
            for slug in project_slugs:
                if project_slug.lower() == slug.lower():
                    return user_preferences.dump()

            # Check if we have reached the maximum number of pins
            if (
                self.user_preferences_config.max_pinned_projects > 0
                and len(project_slugs) >= self.user_preferences_config.max_pinned_projects
            ):
                raise errors.ValidationError(
                    message="Maximum number of pinned projects already allocated"
                    + f" (limit: {self.user_preferences_config.max_pinned_projects}, current: {len(project_slugs)})"
                )

            new_project_slugs = list(project_slugs) + [project_slug]
            pinned_projects = models.PinnedProjects(project_slugs=new_project_slugs).model_dump()
            user_preferences.pinned_projects = pinned_projects
            return user_preferences.dump()

    async def remove_pinned_project(self, user: base_models.APIUser, project_slug: str) -> models.UserPreferences:
        """Removes on or all pinned projects from the user's preferences."""
        async with self.session_maker() as session, session.begin():
            if not user.is_authenticated:
                raise errors.Unauthorized(message="Anonymous users cannot have user preferences.")

            res = await session.scalars(
                select(schemas.UserPreferencesORM).where(schemas.UserPreferencesORM.user_id == user.id)
            )
            user_preferences = res.one_or_none()

            if user_preferences is None:
                raise errors.MissingResourceError(message="Preferences not found for user.")

            project_slugs: list[str]
            project_slugs = user_preferences.pinned_projects.get("project_slugs", [])

            # Remove all projects if `project_slug` is None
            new_project_slugs = (
                [slug for slug in project_slugs if project_slug.lower() != slug.lower()] if project_slug else []
            )

            pinned_projects = models.PinnedProjects(project_slugs=new_project_slugs).model_dump()
            user_preferences.pinned_projects = pinned_projects
            return user_preferences.dump()
