"""Utilities to migrate storages_v2 to data_connectors."""

import random
import string
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only
from ulid import ULID

from renku_data_services import base_models, errors
from renku_data_services.authz.authz import Authz, ResourceType, Role
from renku_data_services.authz.models import Scope
from renku_data_services.base_models.core import Slug
from renku_data_services.data_connectors import models
from renku_data_services.data_connectors.db import DataConnectorRepository
from renku_data_services.namespace.models import NamespaceKind
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

    async def migrate_storage_v2(
        self, requested_by: base_models.APIUser, storage: storage_models.CloudStorage
    ) -> models.DataConnector:
        """Move a storage_v2 entity to the data connectors table."""
        if requested_by.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")
        if not requested_by.is_admin:
            raise errors.ForbiddenError(message="Only admins can perform this operation.")

        project_id = ULID.from_str(storage.project_id)
        project = await self.project_repo.get_project(user=requested_by, project_id=project_id)

        # Find an owner
        data_connector_owner = await self._find_owner(requested_by=requested_by, project=project)
        if data_connector_owner is None:
            raise errors.ProgrammingError(
                message=f"Could not find an owner for storage {storage.name} with project {project_id}."
            )

        # Try to create the data connector with the default slug first
        try:
            data_connector = await self._insert_data_connector(
                user=data_connector_owner, storage=storage, project=project
            )
        except errors.ConflictError:
            # Retry with a random suffix in the slug
            suffix = "".join([random.choice(string.ascii_lowercase + string.digits) for _ in range(8)])  # nosec B311
            data_connector_slug = Slug.from_name(storage.name).value
            data_connector_slug = f"{data_connector_slug}-{suffix}"
            data_connector = await self._insert_data_connector(
                user=data_connector_owner, storage=storage, project=project, data_connector_slug=data_connector_slug
            )

        # Link the data connector to the project
        unsaved_link = models.UnsavedDataConnectorToProjectLink(
            data_connector_id=data_connector.id,
            project_id=project_id,
        )
        await self.data_connector_repo.insert_link(user=data_connector_owner, link=unsaved_link)

        # Remove the storage_v2 from the database
        await self._delete_storage_v2(requested_by=requested_by, storage_id=storage.storage_id)

        return data_connector

    async def _find_owner(
        self, requested_by: base_models.APIUser, project: projects_models.Project
    ) -> base_models.APIUser | None:
        """Find an owner from the project or its namespace."""
        if requested_by.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")
        if not requested_by.is_admin:
            raise errors.ForbiddenError(message="Only admins can perform this operation.")

        # Use the corresponding user in the case of a user namespace
        if project.namespace.kind == NamespaceKind.user:
            user_id = str(project.namespace.underlying_resource_id)
            return base_models.APIUser(is_admin=False, id=user_id)

        if not isinstance(project.namespace.underlying_resource_id, ULID):
            raise errors.ProgrammingError(
                message=f"Group namespace {project.namespace} has an invalid underlying resource id {project.namespace.underlying_resource_id}."  # noqa E501
            )

        group_id = project.namespace.underlying_resource_id
        project_members = await self.authz.members(requested_by, ResourceType.project, project.id)

        # Try with the project creator
        project_creator = next(filter(lambda m: m.user_id == project.created_by, project_members), None)
        if project_creator is not None:
            project_creator_api_user = base_models.APIUser(is_admin=False, id=project_creator.user_id)
            can_create_data_connector = await self.authz.has_permission(
                project_creator_api_user, ResourceType.group, group_id, Scope.WRITE
            )
            if can_create_data_connector:
                return project_creator_api_user

        # Try to find a project owner which can create the data connector
        for member in project_members:
            if member.role != Role.OWNER:
                continue
            member_api_user = base_models.APIUser(is_admin=False, id=member.user_id)
            can_create_data_connector = await self.authz.has_permission(
                member_api_user, ResourceType.group, group_id, Scope.WRITE
            )
            if can_create_data_connector:
                return member_api_user

        # Use any group owner as a last resort
        group_members = await self.authz.members(requested_by, ResourceType.group, group_id)
        found_owner = next(filter(lambda m: m.role == Role.OWNER, group_members), None)
        if found_owner is not None:
            return base_models.APIUser(is_admin=False, id=found_owner.user_id)
        return None

    async def _insert_data_connector(
        self,
        user: base_models.APIUser,
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
            namespace=project.path,
            slug=data_connector_slug,
            visibility=project.visibility,
            created_by="",
            storage=unsaved_storage,
        )

        data_connector = await self.data_connector_repo.insert_data_connector(
            user=user, data_connector=unsaved_data_connector
        )
        if isinstance(data_connector, models.GlobalDataConnector):
            raise errors.ProgrammingError(message="Migration to global data connector should not happen.")
        return data_connector

    async def get_storages_v2(self, requested_by: base_models.APIUser) -> list[storage_models.CloudStorage]:
        """Get the storages associated with a Renku 2.0 project."""
        if requested_by.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")
        if not requested_by.is_admin:
            raise errors.ForbiddenError(message="Only admins can perform this operation.")

        all_project_ids = await self._get_all_project_ids(requested_by=requested_by)
        all_project_ids_str = [str(pid) for pid in all_project_ids]

        async with self.session_maker() as session:
            stmt = select(storage_schemas.CloudStorageORM).where(
                storage_schemas.CloudStorageORM.project_id.in_(all_project_ids_str)
            )
            result = await session.scalars(stmt)
            storages = result.all()
            return [storage.dump() for storage in storages]

    async def _delete_storage_v2(self, requested_by: base_models.APIUser, storage_id: ULID) -> ULID | None:
        """Delete a storage_v2 from the database."""
        if requested_by.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")
        if not requested_by.is_admin:
            raise errors.ForbiddenError(message="Only admins can perform this operation.")

        async with self.session_maker() as session, session.begin():
            result = await session.scalars(
                select(storage_schemas.CloudStorageORM).where(storage_schemas.CloudStorageORM.storage_id == storage_id)
            )
            storage = result.one_or_none()
            if storage is None:
                return None
            await session.delete(storage)
            return storage_id

    async def _get_all_project_ids(self, requested_by: base_models.APIUser) -> list[ULID]:
        """Get all Renku 2.0 projects."""
        if requested_by.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")
        if not requested_by.is_admin:
            raise errors.ForbiddenError(message="Only admins can perform this operation.")

        async with self.session_maker() as session:
            stmt = select(projects_schemas.ProjectORM).options(load_only(projects_schemas.ProjectORM.id))
            result = await session.scalars(stmt)
            return [project.id for project in result]
