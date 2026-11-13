"""Database access for project storage classes."""

from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from sqlalchemy import and_, exists, func, select
from sqlalchemy.ext.asyncio import AsyncScalarResult, AsyncSession
from sqlalchemy.orm import selectinload
from ulid import ULID

from renku_data_services import base_models, errors
from renku_data_services.authz.authz import Authz, ResourceType
from renku_data_services.authz.models import Scope
from renku_data_services.base_api.pagination import PaginationRequest
from renku_data_services.crc import orm as rp_schemas
from renku_data_services.crc.db import StorageQuotaRepository
from renku_data_services.k8s.constants import ClusterId
from renku_data_services.k8s.models import K8sPersistentVolumeClaimV2
from renku_data_services.namespace import orm as ns_schemas
from renku_data_services.namespace.db import GroupRepository
from renku_data_services.project import orm as project_schemas
from renku_data_services.project.db import ProjectRepository
from renku_data_services.project.orm import ProjectORM
from renku_data_services.storage import constants, models
from renku_data_services.storage import orm as schemas
from renku_data_services.storage.config import ProjectStorageConfig
from renku_data_services.utils.core import with_db_session, with_db_transaction

if TYPE_CHECKING:
    from renku_data_services.notebooks.api.classes.k8s_client import NotebookK8sClient


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
        # When the feature is disabled, we disallow insertion, but still allow managing existing data
        if not self.project_storage_config.enabled:
            raise errors.MissingResourceError(message="The project storage api is not enabled.")

        if not session:
            raise errors.ProgrammingError(message="A database session is required.")
        if user.id is None or not user.is_admin:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")

        match input.project_ref.ref:
            case ULID() as id:
                existing_project_query = select(schemas.ProjectORM).where(schemas.ProjectORM.id == id)
            case base_models.ProjectPath() as p:
                existing_project_query = (
                    select(schemas.ProjectORM)
                    .join(
                        ns_schemas.EntitySlugORM,
                        and_(
                            ns_schemas.EntitySlugORM.project_id == schemas.ProjectORM.id,
                            ns_schemas.EntitySlugORM.data_connector_id.is_(None),
                        ),
                    )
                    .join(ns_schemas.NamespaceORM, ns_schemas.NamespaceORM.id == ns_schemas.EntitySlugORM.namespace_id)
                    .where(
                        and_(
                            ns_schemas.NamespaceORM.slug == p.first.value,
                            ns_schemas.EntitySlugORM.slug == p.second.value,
                        )
                    )
                )

        existing_project = await session.execute(existing_project_query)
        existing_project = existing_project.scalar_one_or_none()
        if not existing_project:
            raise errors.MissingResourceError(message=f"The project {input.project_ref} doesn't exist.")

        existing = await session.execute(
            select(exists().where(schemas.ProjectStorageAllowORM.project_id == existing_project.id))
        )
        if existing.scalar():
            raise errors.ValidationError(message=f"Project {existing_project.id} is already in the allow list.")

        if input.max_size > self.project_storage_config.maximum_size:
            raise errors.ValidationError(
                message=(
                    f"The maximum size {input.max_size} exceeds the configured "
                    f"one of {self.project_storage_config.maximum_size}."
                )
            )

        new_allow = schemas.ProjectStorageAllowORM(
            project_id=existing_project.id,
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


class ProjectStorageV2Repository:
    """Repository for project storages v2."""

    def __init__(
        self, session_maker: Callable[..., AsyncSession], storage_quota_repo: StorageQuotaRepository, authz: Authz
    ) -> None:
        self.session_maker = session_maker
        self.storage_quota_repo = storage_quota_repo
        self.authz = authz

    async def get_all_project_storages(
        self,
        session: AsyncSession,
        user: base_models.APIUser,
        project_id: ULID | None = None,
        storage_quota_id: ULID | None = None,
    ) -> AsyncIterator[models.ProjectStorageV2]:
        """Get all visible project storages from the database.

        The result can be filtered with project_id and storage_quota_id.
        """
        stream = await self._get_all_project_storages_orm(
            session=session, user=user, project_id=project_id, storage_quota_id=storage_quota_id
        )
        async for storage_orm in stream:
            yield storage_orm.dump()

    async def _get_all_project_storages_orm(
        self,
        session: AsyncSession,
        user: base_models.APIUser,
        project_id: ULID | None = None,
        storage_quota_id: ULID | None = None,
    ) -> AsyncScalarResult[schemas.ProjectStorageV2ORM]:
        project_ids: list[str]
        if project_id:
            authorized = await self.authz.has_permission(user, ResourceType.project, project_id, Scope.READ)
            project_ids = [str(project_id)] if authorized else []
        else:
            project_ids = await self.authz.resources_with_permission(user, user.id, ResourceType.project, Scope.READ)
        stmt = select(schemas.ProjectStorageV2ORM).order_by(schemas.ProjectStorageV2ORM.id.asc())
        stmt = stmt.where(schemas.ProjectStorageV2ORM.project_id.in_(project_ids))
        if storage_quota_id:
            stmt = stmt.where(schemas.ProjectStorageV2ORM.storage_quota_id == storage_quota_id)
        return await session.stream_scalars(stmt)

    # async def get_all_storage_flavors(
    #     self, session: AsyncSession, user: base_models.APIUser
    # ) -> AsyncIterator[models.StorageFlavor]:
    #     """Get all storage flavors from the database."""
    #     stream = await self._get_all_storage_flavors_orm(session=session, user=user)
    #     async for sf_orm in stream:
    #         yield sf_orm.dump()

    # async def _get_all_storage_flavors_orm(
    #     self, session: AsyncSession, user: base_models.APIUser
    # ) -> AsyncScalarResult[schemas.StorageFlavorORM]:
    #     if user.id is None or not user.is_admin:
    #         raise errors.ForbiddenError(message="You do not have the required permissions for this operation.")
    #     stmt = select(schemas.StorageFlavorORM).order_by(schemas.StorageFlavorORM.id.asc())
    #     return await session.stream_scalars(stmt)

    async def get_project_storage_or_none(
        self, session: AsyncSession, user: base_models.APIUser, storage_id: ULID
    ) -> models.ProjectStorageV2 | None:
        """Get a project storage from the database."""
        storage_orm = await self._get_project_storage_or_none_orm(session=session, user=user, storage_id=storage_id)
        return storage_orm.dump() if storage_orm is not None else None

    async def get_project_storage(
        self, session: AsyncSession, user: base_models.APIUser, storage_id: ULID
    ) -> models.ProjectStorageV2:
        """Get a project storage from the database."""
        storage = await self.get_project_storage_or_none(session=session, user=user, storage_id=storage_id)
        if storage is None:
            raise errors.MissingResourceError(
                message=f"Project storage with ID '{str(storage_id)}' does not exist "
                "or you do not have access to it."
            )
        return storage

    async def _get_project_storage_or_none_orm(
        self, session: AsyncSession, user: base_models.APIUser, storage_id: ULID
    ) -> schemas.ProjectStorageV2ORM | None:
        stmt = select(schemas.ProjectStorageV2ORM).where(schemas.ProjectStorageV2ORM.id == storage_id)
        res = await session.scalars(stmt)
        storage_orm = res.one_or_none()
        if storage_orm is None:
            return None
        authorized = await self.authz.has_permission(user, ResourceType.project, storage_orm.project_id, Scope.READ)
        return storage_orm if authorized else None

    async def get_project_storage_from_project_id_or_none(
        self, session: AsyncSession, user: base_models.APIUser, project_id: ULID
    ) -> models.ProjectStorageV2 | None:
        """Get the unique project storage linked to a specific project ID from the database."""
        storage_orm = await self._get_project_storage_from_project_id_or_none_orm(
            session=session, user=user, project_id=project_id
        )
        return storage_orm.dump() if storage_orm is not None else None

    async def _get_project_storage_from_project_id_or_none_orm(
        self, session: AsyncSession, user: base_models.APIUser, project_id: ULID
    ) -> schemas.ProjectStorageV2ORM | None:
        authorized = await self.authz.has_permission(user, ResourceType.project, project_id, Scope.READ)
        if not authorized:
            return None
        stmt = select(schemas.ProjectStorageV2ORM).where(schemas.ProjectStorageV2ORM.project_id == project_id)
        res = await session.scalars(stmt)
        return res.one_or_none()

    async def insert_project_storage(
        self, session: AsyncSession, user: base_models.APIUser, project_storage: models.UnsavedProjectStorageV2
    ) -> models.ProjectStorageV2:
        """Insert a new project storage into the database."""
        if user.id is None:
            raise errors.ForbiddenError(message="You do not have the required permissions for this operation.")

        project_id = project_storage.project_id
        project_orm = self._get_project_orm_or_none(session=session, user=user, project_id=project_id)
        if project_orm is None:
            raise errors.MissingResourceError(
                message=f"Project with id '{project_id}' does not exist or you do not have access to it."
            )

        authorized = await self.authz.has_permission(user, ResourceType.project, project_id, Scope.DELETE)
        if not authorized:
            raise errors.ForbiddenError(
                message=f"You do not have the required permissions to add storage to project '{project_id}'."
            )

        existing_storage_orm = await self._get_existing_project_storage_or_none_orm(
            session=session, user=user, project_id=project_id
        )
        if existing_storage_orm:
            raise errors.ValidationError(message=f"There is already a project storage for project '{project_id}'.")

        storage_quota = await self.storage_quota_repo.get_storage_quota(
            session=session, user=user, storage_quota_id=project_storage.storage_quota_id
        )
        if project_storage.requested_size_bytes < storage_quota.storage_flavor.min_size_bytes:
            raise errors.ValidationError(
                message=f"The requested storage size ({project_storage.requested_size_bytes}) "
                f"for project '{project_id}' "
                f"is lower than the minimum size of {storage_quota.storage_flavor.min_size_bytes}."
            )
        if project_storage.requested_size_bytes > storage_quota.max_size_bytes:
            raise errors.ValidationError(
                message=f"The requested storage size ({project_storage.requested_size_bytes}) "
                f"for project '{project_id}' "
                f"is higher than the maximum size of {storage_quota.max_size_bytes}."
            )

        # TODO: check remaining size from quota

        storage_orm = schemas.ProjectStorageV2ORM(
            project_id=project_id,
            storage_quota_id=storage_quota.id,
            requested_size=project_storage.requested_size_bytes,
            actual_size=None,
            mount_path=project_storage.mount_path,
            k8s_pvc_name=None,
            k8s_pvc_status=None,
            created_by_id=user.id,
        )

        session.add(storage_orm)
        await session.flush()
        # await session.refresh(sq_orm)
        return storage_orm.dump()

    async def _get_project_orm_or_none(
        self, session: AsyncSession, user: base_models.APIUser, project_id: ULID
    ) -> project_schemas.ProjectORM | None:
        authorized = await self.authz.has_permission(user, ResourceType.project, project_id, Scope.READ)
        if not authorized:
            return None
        stmt = select(project_schemas.ProjectORM).where(project_schemas.ProjectORM.id == project_id)
        res = await session.scalars(stmt)
        return res.one_or_none()

    async def _get_existing_project_storage_or_none_orm(
        self, session: AsyncSession, user: base_models.APIUser, project_id: ULID
    ) -> schemas.ProjectStorageV2ORM | None:
        stmt = select(schemas.ProjectStorageV2ORM).where(schemas.ProjectStorageV2ORM.project_id == project_id)
        res = await session.scalars(stmt)
        return res.one_or_none()

    async def get_or_create_backing_pvc(
        self,
        k8s_client: NotebookK8sClient,
        session: AsyncSession,
        user: base_models.APIUser,
        storage_id: ULID,
        expected_cluster_id: ClusterId,
    ) -> tuple[models.ProjectStorageV2, K8sPersistentVolumeClaimV2]:
        """Get or create the Persistent Volume Claim backing a project storage.

        The expected_cluster_id attribute must correspond to the same cluster where the PVC will be used.
        """
        storage_orm = await self._get_project_storage_or_none_orm(session=session, user=user, storage_id=storage_id)
        if storage_orm is None:
            raise errors.MissingResourceError(
                message=f"Project storage with ID '{storage_id}' does not exist or you do not have access to it."
            )

        # Get the storage class, resource pool and cluster for the project storage
        # NOTE: no authorization: the user can see the storage so we MUST determine the correct attributes for it
        sq_orm = await self._get_storage_quota_and_resource_pool_without_authz_or_none_orm(
            session=session, storage_quota_id=storage_orm.storage_quota_id
        )
        if sq_orm is None:
            raise errors.ProgrammingError(
                message=f"Storage quota with ID '{storage_orm.storage_quota_id}' does not exist "
                f"from project storage '{storage_id}'."
            )
        rp_orm = sq_orm.resource_pool
        cluster_id = ClusterId(rp_orm.cluster_id) if rp_orm.cluster_id is not None else None
        cluster = await k8s_client.cluster_by_id(cluster_id=cluster_id)
        if cluster.id != expected_cluster_id:
            raise errors.ValidationError(
                message=f"Project storage with ID '{storage_id}' cannot be used in cluster '{expected_cluster_id}'."
            )
        namespace = cluster.namespace

        # Check if the PVC should already exist
        if storage_orm.k8s_pvc_name:
            meta = K8sPersistentVolumeClaimV2.meta(
                name=storage_orm.k8s_pvc_name, namespace=namespace, cluster_id=cluster.id
            )
            pvc = await k8s_client.get_persistent_volume_claim_v2(meta)
            if pvc is None:
                raise errors.ProgrammingError(
                    message=f"Storage quota with ID '{storage_orm.storage_quota_id}' has lost its persistent volume."
                )
            # Update the storage attributes from k8s
            async with self._with_locked_project_storage(session=session, storage_orm=storage_orm) as locked_orm:
                locked_orm.k8s_pvc_status = pvc.get_status()
                # _actual_size = pvc.get_actual_size()
                # ? Mhm do we need to parse the size?
                await session.flush()
                await session.refresh(locked_orm)
                return locked_orm.dump(), pvc

        # Create the PVC
        # TODO: handle create_persistent_volume_claim_v2() failure: the PVC may already exist
        async with self._with_locked_project_storage(session=session, storage_orm=storage_orm) as locked_orm:
            k8s_pvc_name = f"{constants.PROJECT_STORAGE_V2_PVC_PREFIX}-{str(locked_orm.id).lower()}"
            new_pvc = K8sPersistentVolumeClaimV2.new(
                name=k8s_pvc_name,
                namespace=namespace,
                cluster=cluster.id,
                access_modes=["ReadWriteMany"],
                storage_class_name=sq_orm.storage_flavor.k8s_storage_class_name,
                size=locked_orm.requested_size,
                labels=dict(),
                annotations={
                    "renku.io/storage_id": str(locked_orm.id),
                    "renku.io/project_id": str(locked_orm.project_id),
                    "renku.io/resource_pool_id": str(rp_orm.id),
                    "renku.io/storage_quota_id": str(sq_orm.id),
                },
            )
            pvc = await k8s_client.create_persistent_volume_claim_v2(new_pvc)
            locked_orm.k8s_pvc_name = k8s_pvc_name
            locked_orm.k8s_pvc_status = pvc.get_status()
            # _actual_size = pvc.get_actual_size()
            # ? Mhm do we need to parse the size?
            await session.flush()
            await session.refresh(locked_orm)
            return locked_orm.dump(), pvc

    @asynccontextmanager
    async def _with_locked_project_storage(
        self, session: AsyncSession, storage_orm: schemas.ProjectStorageV2ORM
    ) -> AsyncGenerator[schemas.ProjectStorageV2ORM]:
        """Lock a project storage for updates."""
        stmt = (
            select(schemas.ProjectStorageV2ORM)
            .where(schemas.ProjectStorageV2ORM.id == storage_orm.id)
            .with_for_update(key_share=True)
        )
        res = await session.scalars(stmt)
        locked_orm = res.one()
        yield locked_orm
        await session.flush()

    async def _get_storage_quota_and_resource_pool_without_authz_or_none_orm(
        self, session: AsyncSession, storage_quota_id: ULID
    ) -> rp_schemas.StorageQuotaORM | None:
        stmt = (
            select(rp_schemas.StorageQuotaORM)
            .where(rp_schemas.StorageQuotaORM.id == storage_quota_id)
            .options(selectinload(schemas.StorageQuotaORM.resource_pool))
        )
        res = await session.scalars(stmt)
        return res.one_or_none()

    async def handle_project_storage_for_session(
        self,
        k8s_client: NotebookK8sClient,
        user: base_models.APIUser,
        project_id: ULID,
        expected_cluster_id: ClusterId,
    ) -> tuple[models.ProjectStorageV2, K8sPersistentVolumeClaimV2] | None:
        """Handle project storage for sessions."""
        async with self.session_maker() as session, session.begin():
            storage = await self.get_project_storage_from_project_id_or_none(
                session=session,
                user=user,
                project_id=project_id,
            )
            if storage is None:
                return None
            pvc = await self.get_or_create_backing_pvc(
                k8s_client=k8s_client,
                session=session,
                user=user,
                storage_id=storage.id,
                expected_cluster_id=expected_cluster_id,
            )
            return pvc

    async def delete_project_storage(
        self,
        k8s_client: NotebookK8sClient,
        session: AsyncSession,
        user: base_models.APIUser,
        storage_id: ULID,
    ) -> None:
        """Delete a project storage from the database."""
        storage_orm = await self._get_project_storage_or_none_orm(session=session, user=user, storage_id=storage_id)
        if storage_orm is None:
            return None
        authorized = await self.authz.has_permission(user, ResourceType.project, storage_orm.project_id, Scope.DELETE)
        if not authorized:
            raise errors.ForbiddenError(
                message="You do not have the required permissions to remove storage "
                f"from project '{storage_orm.project_id}'."
            )

        # Get the storage class, resource pool and cluster for the project storage
        # NOTE: no authorization: the user can delete the storage so we MUST determine the correct attributes for it
        sq_orm = await self._get_storage_quota_and_resource_pool_without_authz_or_none_orm(
            session=session, storage_quota_id=storage_orm.storage_quota_id
        )
        if sq_orm is None:
            raise errors.ProgrammingError(
                message=f"Storage quota with ID '{storage_orm.storage_quota_id}' does not exist "
                f"from project storage '{storage_id}'."
            )
        rp_orm = sq_orm.resource_pool
        cluster_id = ClusterId(rp_orm.cluster_id) if rp_orm.cluster_id is not None else None
        cluster = await k8s_client.cluster_by_id(cluster_id=cluster_id)
        namespace = cluster.namespace

        async with self._with_locked_project_storage(session=session, storage_orm=storage_orm) as locked_orm:
            if storage_orm.k8s_pvc_name:
                meta = K8sPersistentVolumeClaimV2.meta(
                    name=storage_orm.k8s_pvc_name, namespace=namespace, cluster_id=cluster.id
                )
                await k8s_client.get_persistent_volume_claim_v2(meta)

            await session.delete(locked_orm)
            await session.flush()

        return None
