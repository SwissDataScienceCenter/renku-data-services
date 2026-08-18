"""Database access for project storage classes."""

from collections.abc import Callable

from sqlalchemy import and_, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from renku_data_services import base_models, errors
from renku_data_services.authz.authz import Authz, ResourceType
from renku_data_services.authz.models import Scope
from renku_data_services.base_api.pagination import PaginationRequest
from renku_data_services.namespace import orm as ns_schemas
from renku_data_services.namespace.db import GroupRepository
from renku_data_services.project.db import ProjectRepository
from renku_data_services.project.orm import ProjectORM
from renku_data_services.storage import models
from renku_data_services.storage import orm as schemas
from renku_data_services.storage.config import ProjectStorageConfig
from renku_data_services.utils.core import with_db_session, with_db_transaction


class ProjectStorageRepository:
    """Repository for project storage."""

    def __init__(
        self,
        session_maker: Callable[..., AsyncSession],
        authz: Authz,
        project_repo: ProjectRepository,
        group_repo: GroupRepository,
        project_storage_config: ProjectStorageConfig,
    ) -> None:
        self.session_maker = session_maker
        self.authz = authz
        self.project_repo = project_repo
        self.group_repo = group_repo
        self.project_storage_config = project_storage_config

    async def get_storage_to(self, user: base_models.APIUser, project_id: ULID) -> models.ProjectStorage | None:
        """Get a project storage to a project if it exists and the feature is enabled."""

        if not self.project_storage_config.enabled:
            return None
        else:
            return await self._get_storage_to_project(user, project_id)

    async def _get_storage_to_project(
        self, user: base_models.APIUser, project_id: ULID
    ) -> models.ProjectStorage | None:
        """Get a project storage to a project if it exists."""

        if user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")

        async with self.session_maker() as session:
            result_orm = await session.scalars(
                select(schemas.ProjectStorageORM).where(schemas.ProjectStorageORM.project_id == project_id)
            )
            result_orm = result_orm.one_or_none()
            if not result_orm:
                return None

        result = result_orm.dump()
        authorized = await self.authz.has_permission(user, ResourceType.project, result.project_id, Scope.READ)
        if not authorized:
            return None

        return result

    def get_project_storage_config(self) -> ProjectStorageConfig:
        """Return the current config for project storage."""

        return self.project_storage_config

    async def get_project_storage(self, user: base_models.APIUser, storage_id: ULID) -> models.ProjectStorage | None:
        """Get a project storage by its id."""

        if user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")

        async with self.session_maker() as session:
            result_orm = await session.scalars(
                select(schemas.ProjectStorageORM).where(schemas.ProjectStorageORM.id == storage_id)
            )
            result_orm = result_orm.one_or_none()
            if not result_orm:
                return None

        result = result_orm.dump()
        authorized = await self.authz.has_permission(user, ResourceType.project, result.project_id, Scope.READ)
        if not authorized:
            return None

        return result

    @with_db_transaction
    async def insert_project_storage(
        self, user: base_models.APIUser, input: models.UnsavedProjectStorage, *, session: AsyncSession | None = None
    ) -> models.ProjectStorage:
        """Insert a new project storage."""

        # When the feature is disabled, we disallow insertion, but still allow managing existing data
        if not self.project_storage_config.enabled:
            raise errors.MissingResourceError(message="The project storage api is not enabled.")

        if not session:
            raise errors.ProgrammingError(message="A database session is required.")
        if user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")

        # there is only one such storage possible for a project
        project = await self.project_repo.get_project_by_namespace_slug(
            user, input.namespace_path.first.value, input.namespace_path.second, with_documentation=False
        )

        authorized = await self.authz.has_permission(user, ResourceType.project, project.id, Scope.DELETE)
        if not authorized:
            raise errors.MissingResourceError(
                message=f"Project with id '{project.id}' does not exist or you do not have access to it."
            )

        allowed = await session.execute(
            select(schemas.ProjectStorageAllowORM).where(schemas.ProjectStorageAllowORM.project_id == project.id)
        )
        allowed = allowed.scalar()
        if not allowed:
            raise errors.ForbiddenError(message=f"Project storage is not enabled for project {project.id}.")

        existing_storage = await session.execute(
            select(exists().where(schemas.ProjectStorageORM.project_id == project.id))
        )
        existing_storage = existing_storage.scalar()
        if existing_storage:
            raise errors.ValidationError(message=f"There is already a project storage for project {project.id}")

        if input.size > allowed.max_size:
            raise errors.ValidationError(
                message=(
                    f"The project storage size ({input.size}) for project {project.id} "
                    f"exceeds the maximum size of {allowed.max_size}"
                )
            )

        new_storage = schemas.ProjectStorageORM(
            project_id=project.id,
            storage_class=self.project_storage_config.storage_class,
            size_limit=input.size,
            mount_path=input.mount_path,
            created_by_id=user.id,
        )
        session.add(new_storage)
        await session.flush()
        return new_storage.dump()

    @with_db_transaction
    async def update_project_storage(
        self,
        user: base_models.APIUser,
        storage_id: ULID,
        patch: models.ProjectStoragePatch,
        etag: str,
        *,
        session: AsyncSession | None = None,
    ) -> models.ProjectStorage:
        """Update some properties of a project storage entry."""
        if not session:
            raise errors.ProgrammingError(message="A database session is required.")

        result = await session.scalars(
            select(schemas.ProjectStorageORM).where(schemas.ProjectStorageORM.id == storage_id)
        )
        storage_orm = result.one_or_none()
        if storage_orm is None:
            raise errors.MissingResourceError(message=f"Project storage with id '{storage_id}' does not exist.")

        # Check authorization - user must be "owner", meaning allowed to delete the project
        authorized = await self.authz.has_permission(user, ResourceType.project, storage_orm.project_id, Scope.DELETE)
        if not authorized:
            raise errors.MissingResourceError(
                message=f"Project storage with id '{storage_id}' does not exist or you do not have access to it."
            )

        current_storage = storage_orm.dump()
        current_etag = current_storage.etag
        if current_etag != etag:
            raise errors.ConflictError(message=f"Current ETag is {current_etag}, not {etag}.")

        # Check if size would exceed the allowed maximum
        new_size = patch.size if patch.size else current_storage.size
        allowed = await session.execute(
            select(schemas.ProjectStorageAllowORM).where(
                schemas.ProjectStorageAllowORM.project_id == storage_orm.project_id
            )
        )
        allowed = allowed.scalar()
        if allowed and new_size > allowed.max_size:
            raise errors.ValidationError(
                message=(
                    f"The project storage size ({new_size}) for project {storage_orm.project_id} "
                    f"exceeds the maximum size of {allowed.max_size}"
                )
            )

        if patch.size is not None:
            storage_orm.size_limit = patch.size
        if patch.mount_path is not None:
            storage_orm.mount_path = patch.mount_path

        await session.flush()
        await session.refresh(storage_orm)
        return storage_orm.dump()

    @with_db_transaction
    async def insert_project_storage_allow(
        self, user: base_models.APIUser, input: models.ProjectStorageAllow, *, session: AsyncSession | None = None
    ) -> models.ProjectStorageAllow:
        """Insert a new project storage allow entry."""
        if not session:
            raise errors.ProgrammingError(message="A database session is required.")
        if user.id is None or not user.is_admin:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")

        existing = await session.execute(
            select(exists().where(schemas.ProjectStorageAllowORM.project_id == input.project_id))
        )
        if existing.scalar():
            raise errors.ValidationError(message=f"Project {input.project_id} is already in the allow list.")

        existing_project = await session.execute(
            select(exists().where(schemas.ProjectORM.id == input.project_id))
        )
        if not existing_project.scalar():
            raise errors.MissingResourceError(message=f"The project {input.project_id} doesn't exist.")

        if input.max_size > self.project_storage_config.maximum_size:
            raise errors.ValidationError(
                message=(
                    f"The maximum size {input.max_size} exceeds the configured "
                    f"one of {self.project_storage_config.maximum_size}."
                )
            )

        new_allow = schemas.ProjectStorageAllowORM(
            project_id=input.project_id,
            max_size=input.max_size,
        )
        session.add(new_allow)
        await session.flush()
        return new_allow.dump()

    @with_db_transaction
    async def delete_project_storage(
        self, user: base_models.APIUser, storage_id: ULID, *, session: AsyncSession | None = None
    ) -> models.DeletedProjectStorage | None:
        """Delete a specific project storage."""
        if not session:
            raise errors.ProgrammingError(message="A database session is required.")

        result = await session.scalars(
            select(schemas.ProjectStorageORM).where(schemas.ProjectStorageORM.id == storage_id)
        )
        storage_orm = result.one_or_none()
        if storage_orm is None:
            return None

        authorized = await self.authz.has_permission(user, ResourceType.project, storage_orm.project_id, Scope.DELETE)
        if not authorized:
            raise errors.MissingResourceError(
                message=f"Project storage with id '{storage_id}' does not exist or you do not have access to it."
            )

        await session.delete(storage_orm)
        ps = storage_orm.dump()
        return models.DeletedProjectStorage(project_id=ps.project_id)

    @with_db_session
    async def get_project_storage_allow(
        self,
        user: base_models.APIUser,
        project_id: ULID,
        *,
        session: AsyncSession | None = None,
    ) -> models.ProjectStorageAllowDetail | None:
        """Get the storage allow entry for a project if it exists."""
        if not session:
            raise errors.ProgrammingError(message="A database session is required.")

        authorized = await self.authz.has_permission(user, ResourceType.project, project_id, Scope.READ)
        if not authorized:
            raise errors.MissingResourceError(
                message=f"Project with id '{project_id}' does not exist or you do not have access to it."
            )
        stmt = (
            select(
                schemas.ProjectStorageAllowORM.project_id,
                schemas.ProjectStorageAllowORM.max_size,
                ProjectORM.name,
                ns_schemas.NamespaceORM.slug.label("namespace_slug"),
                ns_schemas.EntitySlugORM.slug.label("project_slug"),
                schemas.ProjectStorageAllowORM.updated_at,
            )
            .join(ProjectORM, ProjectORM.id == schemas.ProjectStorageAllowORM.project_id)
            .join(
                ns_schemas.EntitySlugORM,
                and_(
                    ns_schemas.EntitySlugORM.project_id == schemas.ProjectStorageAllowORM.project_id,
                    ns_schemas.EntitySlugORM.data_connector_id.is_(None),
                ),
            )
            .join(ns_schemas.NamespaceORM, ns_schemas.NamespaceORM.id == ns_schemas.EntitySlugORM.namespace_id)
            .where(schemas.ProjectStorageAllowORM.project_id == project_id)
        )
        result = (await session.execute(stmt)).one_or_none()
        if result:
            return models.ProjectStorageAllowDetail.create(**result._mapping)
        return None

    async def get_project_storage_allows(
        self, user: base_models.APIUser, pagination: PaginationRequest, project_name: str | None = None
    ) -> tuple[list[models.ProjectStorageAllowDetail], int]:
        """Get all project storage allow entries, optionally filtered by project name."""
        if user.id is None or not user.is_admin:
            raise errors.ForbiddenError(message="You do not have the required permissions for this operation.")

        async with self.session_maker() as session:
            stmt = (
                select(
                    schemas.ProjectStorageAllowORM.project_id,
                    schemas.ProjectStorageAllowORM.max_size,
                    ProjectORM.name,
                    ns_schemas.NamespaceORM.slug.label("namespace_slug"),
                    ns_schemas.EntitySlugORM.slug.label("project_slug"),
                    schemas.ProjectStorageAllowORM.updated_at,
                )
                .join(ProjectORM, ProjectORM.id == schemas.ProjectStorageAllowORM.project_id)
                .join(
                    ns_schemas.EntitySlugORM,
                    and_(
                        ns_schemas.EntitySlugORM.project_id == schemas.ProjectStorageAllowORM.project_id,
                        ns_schemas.EntitySlugORM.data_connector_id.is_(None),
                    ),
                )
                .join(ns_schemas.NamespaceORM, ns_schemas.NamespaceORM.id == ns_schemas.EntitySlugORM.namespace_id)
            )

            stmt_count = select(func.count()).select_from(schemas.ProjectStorageAllowORM)
            if project_name:
                stmt = stmt.where(ProjectORM.name.ilike(f"%{project_name}%"))
                stmt_count = stmt_count.where(ProjectORM.name.ilike(f"%{project_name}%"))
            stmt = (
                stmt.order_by(schemas.ProjectStorageAllowORM.project_id)
                .limit(pagination.per_page)
                .offset(pagination.offset)
            )
            rows = await session.execute(stmt)
            results = [models.ProjectStorageAllowDetail.create(**row._mapping) for row in rows]
            total = await session.scalar(stmt_count) or 0
            return results, total

    @with_db_transaction
    async def update_project_storage_allow(
        self,
        user: base_models.APIUser,
        project_id: ULID,
        patch: models.ProjectStorageAllowPatch,
        etag: str,
        *,
        session: AsyncSession | None = None,
    ) -> models.ProjectStorageAllowUpdate:
        """Update some properties of a project storage allow entry."""
        if not session:
            raise errors.ProgrammingError(message="A database session is required.")

        old = await self.get_project_storage_allow(user, project_id, session=session)
        ps_orm = await session.scalars(
            select(schemas.ProjectStorageAllowORM).where(schemas.ProjectStorageAllowORM.project_id == project_id)
        )
        ps_orm = ps_orm.one_or_none()
        if not old or not ps_orm or not isinstance(user, base_models.AuthenticatedAPIUser) or not user.is_admin:
            raise errors.MissingResourceError(
                message=(
                    f"Project storage allow entry for project '{project_id}' "
                    "does not exist or you do not have access to it."
                )
            )

        current_etag = old.etag
        if current_etag != etag:
            raise errors.ConflictError(message=f"Current ETag is {current_etag}, not {etag}.")

        if patch.max_size:
            ps_orm.max_size = patch.max_size

        await session.flush()
        await session.refresh(ps_orm)

        new = models.ProjectStorageAllowDetail(
            project_id=project_id,
            max_size=ps_orm.max_size,
            name=old.name,
            namespace_path=old.namespace_path,
            updated_at=ps_orm.updated_at,
        )
        return models.ProjectStorageAllowUpdate(old=old, new=new)

    @with_db_transaction
    async def delete_project_storage_allow(
        self, user: base_models.APIUser, project_id: ULID, *, session: AsyncSession | None = None
    ) -> models.DeletedProjectStorage | None:
        """Delete a project storage allow entry."""
        if not session:
            raise errors.ProgrammingError(message="A database session is required.")

        if user.id is None or not user.is_admin:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")

        storage = await self._get_storage_to_project(user, project_id)
        result = await session.scalars(
            select(schemas.ProjectStorageAllowORM).where(schemas.ProjectStorageAllowORM.project_id == project_id)
        )
        allow_orm = result.one_or_none()
        if allow_orm:
            await session.delete(allow_orm)

        if storage:
            return models.DeletedProjectStorage(project_id=storage.project_id)
        return None
