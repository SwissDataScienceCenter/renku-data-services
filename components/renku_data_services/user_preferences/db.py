"""Adapters for user preferences database classes."""
from typing import List, cast

from sqlalchemy import create_engine, select, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import renku_data_services.base_models as base_models
from renku_data_services import errors
from sanic.log import logger
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
    ) -> models.UserPreferences:
        """Get user preferences from the database."""
        async with cast(AsyncSession, self.session_maker()) as session:
            if not user.is_authenticated:
                raise errors.Unauthorized(message="Anonymous users cannot have user preferences.")

            res = await session.scalars(
                select(schemas.UserPreferencesORM).where(schemas.UserPreferencesORM.user_id == user.id)
            )
            user_preferences = res.one_or_none()

            if user_preferences is None:
                raise errors.MissingResourceError(message="Preferences not found for user.")
            return user_preferences.dump()

    async def add_pinned_project(self, user: base_models.APIUser, project_slug: str) -> models.UserPreferences:
        """Adds a new pinned project to the user's preferences."""
        async with cast(AsyncSession, self.session_maker()) as session:
            async with session.begin():
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
                    result = user_preferences.dump()
                else:
                    project_slugs: List[str]
                    project_slugs = user_preferences.pinned_projects.get("project_slugs", [])

                    exists = False
                    for slug in project_slugs:
                        if project_slug.lower() == slug.lower():
                            exists = True
                            break

                    if exists:
                        result = user_preferences.dump()
                    else:
                        logger.warning(f"(DEBUG): {'|'.join(project_slugs)} + {project_slug}")
                        project_slugs.append(project_slug)
                        logger.warning(f"(DEBUG): {'|'.join(project_slugs)}")
                        pinned_projects = models.PinnedProjects(project_slugs=project_slugs).model_dump()
                        user_preferences.pinned_projects = pinned_projects
                        logger.warning(f"(DEBUG): {user_preferences.dump().model_dump_json()}")
                        result = user_preferences.dump()

        return result

    async def remove_pinned_project(self, user: base_models.APIUser, project_slug: str) -> models.UserPreferences:
        """Adds a pinned project from the user's preferences."""
        async with cast(AsyncSession, self.session_maker()) as session:
            async with session.begin():
                if not user.is_authenticated:
                    raise errors.Unauthorized(message="Anonymous users cannot have user preferences.")

                res = await session.scalars(
                    select(schemas.UserPreferencesORM).where(schemas.UserPreferencesORM.user_id == user.id)
                )
                user_preferences = res.one_or_none()

                if user_preferences is None:
                    raise errors.MissingResourceError(message="Preferences not found for user.")

                project_slugs: List[str]
                project_slugs = user_preferences.pinned_projects.get("project_slugs", [])
                new_project_slugs = [slug for slug in project_slugs if project_slug.lower() != slug.lower()]
                pinned_projects = models.PinnedProjects(project_slugs=new_project_slugs).model_dump()
                setattr(user_preferences, "pinned_projects", pinned_projects)
                return user_preferences.dump()
