"""Utilities to migrate storages_v2 to data_connectors."""

import random
import string
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from renku_data_services import base_models, errors
from renku_data_services.authz.authz import Authz, ResourceType, Role
from renku_data_services.base_models.core import Slug
from renku_data_services.data_connectors import models
from renku_data_services.data_connectors.db import DataConnectorRepository
from renku_data_services.data_connectors import orm as schemas
from renku_data_services.project import models as projects_models
from renku_data_services.project import orm as projects_schemas
from renku_data_services.project.db import ProjectRepository
from renku_data_services.storage import models as storage_models
from renku_data_services.storage import orm as storage_schemas


class DataConnectorMigrationTool:
    """Tool to help migrate storages_v2 to data_connectors."""

    def __init__(
        self,
        session_maker: Callable[..., AsyncSession],
        data_connector_repo: DataConnectorRepository,
        project_repo: ProjectRepository,
        authz: Authz,
    ) -> None:
        self.session_maker = session_maker
        self.data_connector_repo = data_connector_repo
        self.project_repo = project_repo
        self.authz = authz

    async def migrate_storage_v2(self, requested_by: base_models.APIUser, storage: storage_models.CloudStorage) -> None:
        """Move a storage_v2 entity to the data connectors table."""
        if requested_by.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")
        if not requested_by.is_admin:
            raise errors.ForbiddenError(message="Only admins can perform this operation.")

        project_id = ULID.from_str(storage.project_id)
        project = await self.project_repo.get_project(user=requested_by, project_id=project_id)

        # Try to create the data connector with the default slug first
        try:
            data_connector = await self._insert_data_connector(
                requested_by=requested_by, storage=storage, project=project
            )
        except errors.ConflictError:
            # Retry with a random suffix in the slug
            suffix = "".join([random.choice(string.ascii_lowercase + string.digits) for _ in range(8)])
            data_connector_slug = Slug.from_name(storage.name).value
            data_connector_slug = f"{data_connector_slug}-{suffix}"
            data_connector = await self._insert_data_connector(
                requested_by=requested_by, storage=storage, project=project, data_connector_slug=data_connector_slug
            )

        # Adjust the owner
        data_connector_owner = await self._find_owner(requested_by=requested_by, project=project)
        if data_connector_owner:
            pass

        raise NotImplementedError()

    async def _insert_data_connector(
        self,
        requested_by: base_models.APIUser,
        storage: storage_models.CloudStorage,
        project: projects_models.Project,
        data_connector_slug: str | None = None,
    ) -> models.DataConnector:
        """Attemtps to save a data connector with the same properties as the given storage_v2."""
        data_connector_slug = data_connector_slug if data_connector_slug else Slug.from_name(storage.name).value

        unsaved_storage = models.CloudStorageCore(
            storage_type=storage.storage_type,
            configuration=storage.configuration.config,
            source_path=storage.source_path,
            target_path=storage.target_path,
            readonly=storage.readonly,
        )
        unsaved_data_connector = models.UnsavedDataConnector(
            name=storage.name,
            namespace=project.namespace.slug,
            slug=data_connector_slug,
            visibility=project.visibility,
            created_by="",
            storage=unsaved_storage,
        )

        data_connector = await self.data_connector_repo.insert_data_connector(
            user=requested_by, data_connector=unsaved_data_connector
        )
        return data_connector

    async def _find_owner(self, requested_by: base_models.APIUser, project: projects_models.Project) -> str | None:
        """Find the owner of a project, defaulting to its creator if possible."""
        if requested_by.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")
        if not requested_by.is_admin:
            raise errors.ForbiddenError(message="Only admins can perform this operation.")

        owners = await self.authz.members(requested_by, ResourceType.project, project.id, Role.OWNER)
        creator = next(filter(lambda owner: owner.user_id == project.created_by, owners), None)
        if creator is not None:
            return creator.user_id
        if owners:
            return owners[0].user_id
        # TODO: Log warning f"Project owner list is empty for project {project.id}."
        return None
    
    # async def _update_owner(self, )

    async def _get_storages_v2(self, requested_by: base_models.APIUser) -> list[storage_models.CloudStorage]:
        """Get the storages associated with a Renku 2.0 project."""
        if requested_by.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")
        if not requested_by.is_admin:
            raise errors.ForbiddenError(message="Only admins can perform this operation.")

        all_project_ids = await self._get_all_project_ids(requested_by=requested_by)

        async with self.session_maker() as session:
            stmt = select(storage_schemas.CloudStorageORM).where(
                storage_schemas.CloudStorageORM.project_id.in_(all_project_ids)
            )
            result = await session.scalars(stmt)
            storages = result.all()
            return [storage.dump() for storage in storages]

    async def _get_all_project_ids(self, requested_by: base_models.APIUser) -> list[ULID]:
        """Get all Renku 2.0 projects."""
        if requested_by.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")
        if not requested_by.is_admin:
            raise errors.ForbiddenError(message="Only admins can perform this operation.")

        async with self.session_maker() as session:
            stmt = select(projects_schemas.ProjectORM)
            result = await session.scalars(stmt)
            projects = result.all()
            return [project.dump().id for project in projects]
