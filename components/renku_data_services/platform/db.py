"""Adapters for platform config database classes."""

from collections.abc import AsyncGenerator, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from renku_data_services import base_models, errors
from renku_data_services.authz.authz import Authz, AuthzOperation, ResourceType
from renku_data_services.base_api.pagination import PaginationRequest
from renku_data_services.platform import models
from renku_data_services.platform import orm as schemas
from renku_data_services.project.db import ProjectRepository


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


class RedirectRepository:
    """Repository for redirects."""

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
        pagination: PaginationRequest,
    ) -> tuple[list[models.UrlRedirectConfig], int]:
        """Get all redirect configs from the database."""
        project_ids = await self.authz.resources_with_permission(user, user.id, ResourceType.project, Scope.READ)

        async with self.session_maker() as session:
            stmt = select(schemas.ProjectMigrationsORM).where(schemas.ProjectMigrationsORM.project_id.in_(project_ids))
            result = await session.stream_scalars(stmt)
            async for migration in result:
                yield migration.dump()

    @with_db_transaction
    @Authz.authz_change(AuthzOperation.create, ResourceType.project)
    async def migrate_v1_project(
        self,
        user: base_models.APIUser,
        project: models.UnsavedProject,
        project_v1_id: int,
        session_launcher: project_apispec.MigrationSessionLauncherPost | None = None,
        session: AsyncSession | None = None,
    ) -> models.Project:
        """Migrate a v1 project by creating a new project and tracking the migration."""
        if not session:
            raise errors.ProgrammingError(message="A database session is required")

        result = await session.scalars(
            select(schemas.ProjectMigrationsORM).where(schemas.ProjectMigrationsORM.project_v1_id == project_v1_id)
        )
        project_migration = result.one_or_none()
        if project_migration is not None:
            raise errors.ValidationError(message=f"Project V1 with id '{project_v1_id}' already exists.")
        created_project = await self.project_repo.insert_project(user, project)
        if not created_project:
            raise errors.ValidationError(
                message=f"Failed to create a project for migration from v1 (project_v1_id={project_v1_id})."
            )

        result_launcher = None
        if session_launcher is not None:
            unsaved_session_launcher = session_apispec.SessionLauncherPost(
                name=session_launcher.name,
                project_id=str(created_project.id),
                description=None,
                resource_class_id=session_launcher.resource_class_id,
                disk_storage=session_launcher.disk_storage,
                environment=session_apispec.EnvironmentPostInLauncherHelper(
                    environment_kind=session_apispec.EnvironmentKind.CUSTOM,
                    name=session_launcher.name,
                    description=None,
                    container_image=session_launcher.container_image,
                    default_url=session_launcher.default_url,
                    uid=constants.MIGRATION_UID,
                    gid=constants.MIGRATION_GID,
                    working_directory=constants.MIGRATION_WORKING_DIRECTORY,
                    mount_directory=constants.MIGRATION_MOUNT_DIRECTORY,
                    port=constants.MIGRATION_PORT,
                    command=constants.MIGRATION_COMMAND,
                    args=constants.MIGRATION_ARGS,
                    is_archived=False,
                    environment_image_source=session_apispec.EnvironmentImageSourceImage.image,
                    strip_path_prefix=False,
                ),
                env_variables=None,
            )

            new_launcher = validate_unsaved_session_launcher(
                unsaved_session_launcher, builds_config=self.session_repo.builds_config
            )
            result_launcher = await self.session_repo.insert_launcher(user=user, launcher=new_launcher)

        migration_orm = schemas.ProjectMigrationsORM(
            project_id=created_project.id,
            project_v1_id=project_v1_id,
            launcher_id=result_launcher.id if result_launcher else None,
        )

        if migration_orm.project_id is None:
            raise errors.ValidationError(message="Project ID cannot be None for the migration entry.")

        session.add(migration_orm)
        await session.flush()
        await session.refresh(migration_orm)

        return created_project

    async def get_migration_by_v1_id(self, user: base_models.APIUser, v1_id: int) -> models.Project:
        """Retrieve all migration records for a given project v1 ID."""
        async with self.session_maker() as session:
            stmt = select(schemas.ProjectMigrationsORM).where(schemas.ProjectMigrationsORM.project_v1_id == v1_id)
            result = await session.execute(stmt)
            project_ids = result.scalars().first()

            if not project_ids:
                raise errors.MissingResourceError(message=f"Migration for project v1 with id '{v1_id}' does not exist.")

            # NOTE: Show only those projects that user has access to
            allowed_projects = await self.authz.resources_with_permission(
                user, user.id, ResourceType.project, Scope.READ
            )
            project_id_list = [project_ids.project_id]
            stmt = select(schemas.ProjectORM)
            stmt = stmt.where(schemas.ProjectORM.id.in_(project_id_list))
            stmt = stmt.where(schemas.ProjectORM.id.in_(allowed_projects))
            result = await session.execute(stmt)
            project_orm = result.scalars().first()

            if project_orm is None:
                raise errors.MissingResourceError(
                    message="Project migrated does not exist or you don't have permissions to open it."
                )

            return project_orm.dump()

    async def get_migration_by_project_id(
        self, user: base_models.APIUser, project_id: ULID
    ) -> models.ProjectMigrationInfo | None:
        """Retrieve migration info for a given project v2 ID."""

        if user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")

        project_ids = await self.authz.resources_with_permission(user, user.id, ResourceType.project, Scope.WRITE)

        async with self.session_maker() as session:
            stmt_project = select(schemas.ProjectORM.id).where(schemas.ProjectORM.id == project_id)
            stmt_project = stmt_project.where(schemas.ProjectORM.id.in_(project_ids))
            res_project = await session.scalar(stmt_project)
            if not res_project:
                raise errors.MissingResourceError(
                    message=f"Project with ID {project_id} does not exist or you do not have access to it."
                )

            stmt = select(schemas.ProjectMigrationsORM).where(schemas.ProjectMigrationsORM.project_id == project_id)
            result = await session.execute(stmt)
            project_migration_orm = result.scalars().first()

            if project_migration_orm:
                return models.ProjectMigrationInfo(
                    project_id=project_id,
                    v1_id=project_migration_orm.project_v1_id,
                    launcher_id=project_migration_orm.launcher_id,
                )

            return None
