"""Adapters for platform config database classes."""

from collections.abc import Callable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from renku_data_services import base_models, errors
from renku_data_services.authz.authz import Authz, ResourceType
from renku_data_services.base_api.pagination import PaginationRequest
from renku_data_services.platform import models
from renku_data_services.platform import orm as schemas
from renku_data_services.project.db import ProjectRepository

# from renku_data_services.utils.core import with_db_transaction


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
        project_repo: ProjectRepository,
    ) -> None:
        self.session_maker = session_maker
        self.authz = authz
        self.project_repo = project_repo

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
            redirects = results[0].all()
            return [r.dump() for r in redirects], results[1] or 0

    async def get_redirect_config_by_src_url(
        self, user: base_models.APIUser, src_url: str
    ) -> models.UrlRedirectConfig | None:
        """Retrieve redirect config for a given source URL."""

        if user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")

        # We do not currently check if the user is allowed to access the project, but we could...

        async with self.session_maker() as session:
            stmt_project = select(schemas.UrlRedirectsORM.source_url).where(
                schemas.UrlRedirectsORM.source_url == src_url
            )
            res_project = await session.scalar(stmt_project)
            if not res_project:
                raise errors.MissingResourceError(
                    message=f"Redirect config for source URL {src_url} does not exist or you do not have access to it."
                )

            stmt = select(schemas.UrlRedirectsORM).where(schemas.UrlRedirectsORM.source_url == src_url)
            result = await session.execute(stmt)
            url_redirect_orm = result.scalars().first()

            if url_redirect_orm:
                return url_redirect_orm.dump()

            return None
