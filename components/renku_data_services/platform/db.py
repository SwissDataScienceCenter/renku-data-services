"""Adapters for platform config database classes."""

from collections.abc import Callable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from renku_data_services import base_models, errors
from renku_data_services.authz.authz import Authz
from renku_data_services.base_api.pagination import PaginationRequest
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


class UrlRedirectRepository:
    """Repository for URL redirects."""

    def __init__(
        self,
        session_maker: Callable[..., AsyncSession],
        authz: Authz,
    ) -> None:
        self.session_maker = session_maker
        self.authz = authz

    async def _get_redirect_config_by_source_url(
        self, session: AsyncSession, source_url: str
    ) -> schemas.UrlRedirectsORM | None:
        stmt = select(schemas.UrlRedirectsORM).where(schemas.UrlRedirectsORM.source_url == source_url)
        result = await session.execute(stmt)
        config: schemas.UrlRedirectsORM | None = result.scalar_one_or_none()
        return config

    async def get_redirect_configs(
        self,
        user: base_models.APIUser,
        pagination: PaginationRequest,
    ) -> tuple[list[models.UrlRedirectConfig], int]:
        """Get all url redirect configs from the database."""
        if user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")
        if not user.is_admin:
            raise errors.ForbiddenError(message="You do not have the required permissions for this operation.")

        async with self.session_maker() as session:
            stmt = select(schemas.UrlRedirectsORM)
            stmt.limit(pagination.per_page).offset(pagination.offset)
            stmt_count = select(func.count()).select_from(schemas.UrlRedirectsORM)
            results = await session.stream_scalars(stmt), await session.scalar(stmt_count)
            redirects = await results[0].all()
            return [r.dump() for r in redirects], results[1] or 0

    async def get_redirect_config_by_source_url(
        self, user: base_models.APIUser, source_url: str
    ) -> models.UrlRedirectConfig:
        """Retrieve redirect config for a given source URL."""

        if user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")

        async with self.session_maker() as session:
            url_redirect_orm = await self._get_redirect_config_by_source_url(session, source_url)

            if not url_redirect_orm:
                raise errors.MissingResourceError(
                    message=f"A redirect for '{source_url}' does not exist or you do not have access to it."
                )
            return url_redirect_orm.dump()

    async def create_redirect_config(
        self, user: base_models.APIUser, post: models.UnsavedUrlRedirectConfig
    ) -> models.UrlRedirectConfig:
        """Create a new URL redirect config."""
        if user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")
        if not user.is_admin:
            raise errors.ForbiddenError(message="You do not have the required permissions for this operation.")

        async with self.session_maker() as session, session.begin():
            existing = await self._get_redirect_config_by_source_url(session, post.source_url)
            if existing is not None:
                raise errors.ConflictError(message=f"A redirect for source URL '{post.source_url}' already exists.")

            redirect_orm = schemas.UrlRedirectsORM(
                source_url=post.source_url,
                target_url=post.target_url,
            )
            session.add(redirect_orm)
            await session.flush()
            await session.refresh(redirect_orm)
            return redirect_orm.dump()

    async def delete_redirect_config(
        self, user: base_models.APIUser, etag: str, source_url: str
    ) -> models.UrlRedirectUpdateConfig:
        """Update a URL redirect configuration."""
        if user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")
        if not user.is_admin:
            raise errors.ForbiddenError(message="You do not have the required permissions for this operation.")

        async with self.session_maker() as session, session.begin():
            existing = await self._get_redirect_config_by_source_url(session, source_url)
            if existing is None:
                return models.UrlRedirectUpdateConfig(
                    source_url=source_url,
                    target_url=None,
                )

            current_etag = existing.dump().etag
            if current_etag != etag:
                raise errors.ConflictError(message=f"Current ETag is {current_etag}, not {etag}.")

            await session.delete(existing)
            return models.UrlRedirectUpdateConfig(
                source_url=source_url,
                target_url=None,
            )

    async def update_redirect_config(
        self, user: base_models.APIUser, etag: str, patch: models.UrlRedirectUpdateConfig
    ) -> models.UrlRedirectConfig:
        """Update a URL redirect configuration."""
        if user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")
        if not user.is_admin:
            raise errors.ForbiddenError(message="You do not have the required permissions for this operation.")

        async with self.session_maker() as session, session.begin():
            existing = await self._get_redirect_config_by_source_url(session, patch.source_url)
            if existing is None:
                raise errors.MissingResourceError(
                    message=f"A redirect for source URL '{patch.source_url}' does not exist."
                )

            current_etag = existing.dump().etag
            if current_etag != etag:
                raise errors.ConflictError(message=f"Current ETag is {current_etag}, not {etag}.")
            if patch.target_url is not None:
                existing.target_url = patch.target_url
                session.add(existing)
                await session.flush()
                await session.refresh(existing)
            return existing.dump()
