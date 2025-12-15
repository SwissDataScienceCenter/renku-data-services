"""Adapters for data connectors database classes."""

import random
import string
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import TypeVar

from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import ColumnExpressionArgument, Select, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from ulid import ULID

from renku_data_services import base_models, errors
from renku_data_services.authz.authz import Authz, AuthzOperation, ResourceType
from renku_data_services.authz.models import CheckPermissionItem, Scope
from renku_data_services.base_api.pagination import PaginationRequest
from renku_data_services.base_models.core import (
    DataConnectorInProjectPath,
    DataConnectorPath,
    DataConnectorSlug,
    InternalServiceAdmin,
    NamespacePath,
    NamespaceSlug,
    ProjectPath,
    ProjectSlug,
)
from renku_data_services.data_connectors import apispec, models
from renku_data_services.data_connectors import orm as schemas
from renku_data_services.data_connectors.core import validate_unsaved_global_data_connector
from renku_data_services.namespace import orm as ns_schemas
from renku_data_services.namespace.db import GroupRepository
from renku_data_services.namespace.models import ProjectNamespace
from renku_data_services.project.db import ProjectRepository
from renku_data_services.project.models import Project
from renku_data_services.project.orm import ProjectORM
from renku_data_services.search.db import SearchUpdatesRepo
from renku_data_services.search.decorators import update_search_document
from renku_data_services.secrets import orm as secrets_schemas
from renku_data_services.secrets.models import SecretKind
from renku_data_services.storage.rclone import RCloneValidator
from renku_data_services.users.db import UserRepo
from renku_data_services.utils.core import with_db_transaction


class DataConnectorRepository:
    """Repository for data connectors."""

    def __init__(
        self,
        session_maker: Callable[..., AsyncSession],
        authz: Authz,
        project_repo: ProjectRepository,
        group_repo: GroupRepository,
        search_updates_repo: SearchUpdatesRepo,
    ) -> None:
        self.session_maker = session_maker
        self.authz = authz
        self.project_repo = project_repo
        self.group_repo = group_repo
        self.search_updates_repo = search_updates_repo

    async def get_data_connectors(
        self,
        user: base_models.APIUser,
        pagination: PaginationRequest,
        namespace: ProjectPath | NamespacePath | None = None,
    ) -> tuple[list[models.DataConnector | models.GlobalDataConnector], int]:
        """Get multiple data connectors from the database."""

        async def restrict_by_read(stmt: Select) -> Select:
            if isinstance(user, InternalServiceAdmin):
                return stmt
            else:
                dc_ids = await self.authz.resources_with_permission(
                    user, user.id, ResourceType.data_connector, Scope.READ
                )
                return stmt.where(schemas.DataConnectorORM.id.in_(dc_ids))

        async with self.session_maker() as session:
            stmt = (await restrict_by_read(select(schemas.DataConnectorORM))).options(
                joinedload(schemas.DataConnectorORM.slug)
                .joinedload(ns_schemas.EntitySlugORM.project)
                .joinedload(ProjectORM.slug)
            )
            if namespace:
                stmt = _filter_by_namespace_slug(stmt, namespace)
            stmt = stmt.limit(pagination.per_page).offset(pagination.offset)
            stmt = stmt.order_by(schemas.DataConnectorORM.id.desc())
            stmt_count = await restrict_by_read(select(func.count()).select_from(schemas.DataConnectorORM))
            if namespace:
                stmt_count = _filter_by_namespace_slug(stmt_count, namespace)
            results = await session.scalars(stmt), await session.scalar(stmt_count)
            data_connectors = results[0].all()
            total_elements = results[1] or 0
            return [dc.dump() for dc in data_connectors], total_elements

    async def get_data_connector(
        self,
        user: base_models.APIUser,
        data_connector_id: ULID,
    ) -> models.DataConnector | models.GlobalDataConnector:
        """Get one data connector from the database."""
        not_found_msg = f"Data connector with id '{data_connector_id}' does not exist or you do not have access to it."

        authorized = await self.authz.has_permission(user, ResourceType.data_connector, data_connector_id, Scope.READ)
        if not authorized:
            raise errors.MissingResourceError(message=not_found_msg)

        async with self.session_maker() as session:
            result = await session.scalars(
                select(schemas.DataConnectorORM)
                .where(schemas.DataConnectorORM.id == data_connector_id)
                .options(
                    joinedload(schemas.DataConnectorORM.slug)
                    .joinedload(ns_schemas.EntitySlugORM.project)
                    .joinedload(ProjectORM.slug)
                )
            )
            data_connector = result.one_or_none()
            if data_connector is None:
                raise errors.MissingResourceError(message=not_found_msg)
            return data_connector.dump()

    async def get_data_connectors_names_and_ids(
        self,
        user: base_models.APIUser,
        data_connector_ids: list[ULID],
    ) -> list[tuple[str, str]]:
        """Get names of the data connectors.

        Don't check permissions for logged-in users since this is used to get names when users cannot copy data
        connectors due to lack of permission.
        """
        if user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")

        async with self.session_maker() as session:
            stmt = select(schemas.DataConnectorORM).where(schemas.DataConnectorORM.id.in_(data_connector_ids))
            result = await session.scalars(stmt)
            data_connectors_orms = result.all()

        return [
            (dc.name, f"{dc.slug.namespace.slug}/{dc.slug.slug}" if dc.slug is not None else f"{dc.global_slug}")
            for dc in data_connectors_orms
        ]

    async def get_data_connector_by_slug(
        self,
        user: base_models.APIUser,
        path: DataConnectorInProjectPath | DataConnectorPath,
    ) -> models.DataConnector | models.GlobalDataConnector:
        """Get one data connector from the database by slug.

        This will not return or find data connectors owned by projects.
        """
        not_found_msg = (
            f"Data connector with identifier '{path.serialize()}' does not exist or you do not have access to it."
        )

        async with self.session_maker() as session:
            stmt = select(schemas.DataConnectorORM)
            stmt = _filter_by_namespace_slug(stmt, path.parent())
            stmt = stmt.where(
                schemas.DataConnectorORM.slug.has(
                    ns_schemas.EntitySlugORM.slug == path.last().value.lower(),
                )
            )
            result = await session.scalars(stmt)
            data_connector = result.one_or_none()

            if data_connector is None:
                # Try to find the slugs passed in the tables of old slugs
                queries = _old_data_connector_slug_queries(path)
                for query in queries:
                    result_old = await session.scalar(query)
                    if result_old is not None:
                        data_connector = result_old
                        break

            if data_connector is None:
                raise errors.MissingResourceError(message=not_found_msg)

            authorized = await self.authz.has_permission(
                user=user,
                resource_type=ResourceType.data_connector,
                resource_id=data_connector.id,
                scope=Scope.READ,
            )
            if not authorized:
                raise errors.MissingResourceError(message=not_found_msg)

            return data_connector.dump()

    async def get_global_data_connector_by_slug(
        self,
        user: base_models.APIUser,
        slug: base_models.Slug,
    ) -> models.DataConnector | models.GlobalDataConnector:
        """Get one global data connector from the database by slug."""
        not_found_msg = f"Data connector with identifier '{slug}' does not exist or you do not have access to it."

        async with self.session_maker() as session:
            stmt = select(schemas.DataConnectorORM).where(schemas.DataConnectorORM.global_slug == slug.value.lower())
            result = await session.scalars(stmt)
            data_connector = result.one_or_none()

            # TODO: find from old slug for global data connectors
            if data_connector is None:
                raise errors.MissingResourceError(message=not_found_msg)

            authorized = await self.authz.has_permission(
                user=user,
                resource_type=ResourceType.data_connector,
                resource_id=data_connector.id,
                scope=Scope.READ,
            )
            if not authorized:
                raise errors.MissingResourceError(message=not_found_msg)

            return data_connector.dump()

    @with_db_transaction
    @Authz.authz_change(AuthzOperation.create, ResourceType.data_connector)
    @update_search_document
    async def _insert_data_connector(
        self,
        user: base_models.APIUser,
        data_connector: models.UnsavedDataConnector | models.UnsavedGlobalDataConnector,
        *,
        session: AsyncSession | None = None,
    ) -> models.DataConnector | models.GlobalDataConnector:
        """Insert a new data connector entry."""
        if not session:
            raise errors.ProgrammingError(message="A database session is required.")
        ns: ns_schemas.NamespaceORM | None = None
        if isinstance(data_connector, models.UnsavedDataConnector):
            ns = await session.scalar(
                select(ns_schemas.NamespaceORM).where(
                    ns_schemas.NamespaceORM.slug == data_connector.namespace.first.value.lower()
                )
            )
            if not ns:
                raise errors.MissingResourceError(
                    message=f"The data connector cannot be created because the namespace {data_connector.namespace} does not exist."  # noqa E501
                )
            if not ns.group_id and not ns.user_id:
                raise errors.ProgrammingError(message="Found a namespace that has no group or user associated with it.")

        if user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")

        project: Project | None = None
        if ns is None:
            pass
        elif isinstance(data_connector.namespace, ProjectPath):
            error_msg = (
                f"The project with slug {data_connector.namespace} does not exist or you do not have access to it."
            )
            project_slug = await session.scalar(
                select(ns_schemas.EntitySlugORM)
                .where(ns_schemas.EntitySlugORM.namespace_id == ns.id)
                .where(ns_schemas.EntitySlugORM.slug == data_connector.namespace.second.value.lower())
                .where(ns_schemas.EntitySlugORM.project_id.is_not(None))
                .where(ns_schemas.EntitySlugORM.data_connector_id.is_(None))
            )
            if not project_slug or not project_slug.project_id:
                raise errors.MissingResourceError(message=error_msg)
            if project_slug.dump_project_namespace().path != data_connector.namespace:
                raise errors.ProgrammingError(
                    message=f"Mismatched project slug '{project_slug.dump_project_namespace().path}' and data connector namespace '{data_connector.namespace}'"  # noqa E501
                )
            project = await self.project_repo.get_project(user, project_slug.project_id)
            if not project:
                raise errors.MissingResourceError(message=error_msg)
            resource_type = ResourceType.project
            resource_id = project.id
        elif ns.group and ns.group_id:
            resource_type, resource_id = (ResourceType.group, ns.group_id)
        else:
            resource_type, resource_id = (ResourceType.user_namespace, ns.id)

        if ns is not None:
            has_permission = await self.authz.has_permission(user, resource_type, resource_id, Scope.WRITE)
            if not has_permission:
                error_msg = f"The data connector cannot be created because you do not have sufficient permissions with the namespace {data_connector.namespace}"  # noqa: E501
                if isinstance(data_connector.namespace, ProjectPath):
                    error_msg = f"The data connector cannot be created because you do not have sufficient permissions with the project {data_connector.namespace}"  # noqa: E501
                raise errors.ForbiddenError(message=error_msg)

        slug = data_connector.slug or base_models.Slug.from_name(data_connector.name).value

        if ns is not None and isinstance(data_connector, models.UnsavedDataConnector):
            existing_slug_stmt = (
                select(ns_schemas.EntitySlugORM)
                .where(ns_schemas.EntitySlugORM.namespace_id == ns.id)
                .where(ns_schemas.EntitySlugORM.slug == slug)
                .where(ns_schemas.EntitySlugORM.data_connector_id.is_not(None))
            )
            if project:
                existing_slug_stmt = existing_slug_stmt.where(ns_schemas.EntitySlugORM.project_id == project.id)
            else:
                existing_slug_stmt = existing_slug_stmt.where(ns_schemas.EntitySlugORM.project_id.is_(None))
            existing_slug = await session.scalar(existing_slug_stmt)
            if existing_slug is not None:
                raise errors.ConflictError(message=f"An entity with the slug '{data_connector.path}' already exists.")
        elif isinstance(data_connector, models.UnsavedGlobalDataConnector):
            existing_global_dc_stmt = select(schemas.DataConnectorORM).where(
                schemas.DataConnectorORM.global_slug == slug
            )
            existing_global_dc = await session.scalar(existing_global_dc_stmt)
            if existing_global_dc is not None:
                raise errors.ConflictError(message=f"An entity with the slug '{data_connector.slug}' already exists.")

        visibility_orm = (
            apispec.Visibility(data_connector.visibility)
            if isinstance(data_connector.visibility, str)
            else apispec.Visibility(data_connector.visibility.value)
        )
        data_connector_orm = schemas.DataConnectorORM(
            name=data_connector.name,
            visibility=visibility_orm,
            storage_type=data_connector.storage.storage_type,
            configuration=data_connector.storage.configuration,
            source_path=data_connector.storage.source_path,
            target_path=data_connector.storage.target_path,
            readonly=data_connector.storage.readonly,
            created_by_id=user.id,
            description=data_connector.description,
            keywords=data_connector.keywords,
            global_slug=slug if isinstance(data_connector, models.UnsavedGlobalDataConnector) else None,
        )
        if ns is not None:
            data_connector_slug = ns_schemas.EntitySlugORM.create_data_connector_slug(
                slug,
                data_connector_id=data_connector_orm.id,
                namespace_id=ns.id,
                project_id=project.id if project else None,
            )

        session.add(data_connector_orm)
        if ns is not None:
            session.add(data_connector_slug)
        await session.flush()
        await session.refresh(data_connector_orm)
        if ns is not None:
            await session.refresh(data_connector_slug)
        if project:
            await session.refresh(data_connector_slug.project)

        return data_connector_orm.dump()

    @with_db_transaction
    async def insert_namespaced_data_connector(
        self,
        user: base_models.APIUser,
        data_connector: models.UnsavedDataConnector,
        *,
        session: AsyncSession | None = None,
    ) -> models.DataConnector:
        """Insert a new namespaced data connector entry."""
        dc = await self._insert_data_connector(user=user, data_connector=data_connector, session=session)
        if not isinstance(dc, models.DataConnector):
            raise errors.ProgrammingError(message=f"Expected to get a namespaced data connector ('{dc.id}')")
        return dc

    @with_db_transaction
    async def insert_global_data_connector(
        self,
        user: base_models.APIUser,
        data_connector: models.UnsavedGlobalDataConnector,
        validator: RCloneValidator | None,
        *,
        session: AsyncSession | None = None,
    ) -> tuple[models.GlobalDataConnector, bool]:
        """Insert a new global data connector entry."""
        if not session:
            raise errors.ProgrammingError(message="A database session is required.")
        if user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")

        slug = data_connector.slug or base_models.Slug.from_name(data_connector.name).value

        existing_global_dc_stmt = select(schemas.DataConnectorORM).where(schemas.DataConnectorORM.global_slug == slug)
        existing_global_dc = await session.scalar(existing_global_dc_stmt)
        if existing_global_dc is not None:
            dc = existing_global_dc.dump()
            if not isinstance(dc, models.GlobalDataConnector):
                raise errors.ProgrammingError(message=f"Expected to get a global data connector ('{dc.id}')")
            authorized = await self.authz.has_permission(user, ResourceType.data_connector, dc.id, Scope.READ)
            if not authorized:
                raise errors.MissingResourceError(
                    message=f"Data connector with id '{dc.id}' does not exist or you do not have access to it."
                )
            return dc, False

        # Fully validate a global data connector before inserting
        if isinstance(data_connector, models.UnsavedGlobalDataConnector):
            if validator is None:
                raise RuntimeError("Could not validate global data connector")
            data_connector = await validate_unsaved_global_data_connector(
                data_connector=data_connector, validator=validator
            )

        dc = await self._insert_data_connector(user=user, data_connector=data_connector, session=session)
        if not isinstance(dc, models.GlobalDataConnector):
            raise errors.ProgrammingError(message=f"Expected to get a global data connector ('{dc.id}')")
        return dc, True

    @with_db_transaction
    @Authz.authz_change(AuthzOperation.update, ResourceType.data_connector)
    @update_search_document
    async def update_data_connector(
        self,
        user: base_models.APIUser,
        data_connector_id: ULID,
        patch: models.DataConnectorPatch,
        etag: str,
        *,
        session: AsyncSession | None = None,
    ) -> models.DataConnectorUpdate:
        """Update a data connector entry."""
        not_found_msg = f"Data connector with id '{data_connector_id}' does not exist or you do not have access to it."

        if not session:
            raise errors.ProgrammingError(message="A database session is required.")
        result = await session.scalars(
            select(schemas.DataConnectorORM)
            .where(schemas.DataConnectorORM.id == data_connector_id)
            .options(
                joinedload(schemas.DataConnectorORM.slug)
                .joinedload(ns_schemas.EntitySlugORM.project)
                .joinedload(ProjectORM.slug)
            )
        )
        data_connector = result.one_or_none()
        if data_connector is None:
            raise errors.MissingResourceError(message=not_found_msg)
        old_data_connector = data_connector.dump()
        # if old_data_connector.namespace is None:
        #     raise NotImplementedError("Update not supported yet.")
        old_data_connector_parent = (
            old_data_connector.path.parent() if isinstance(old_data_connector, models.DataConnector) else None
        )

        if isinstance(old_data_connector, models.GlobalDataConnector) and patch.namespace:
            raise errors.ValidationError(message="Moving a global data connector into a namespace is not supported.")

        required_scope = Scope.WRITE
        if patch.visibility is not None and patch.visibility != old_data_connector.visibility:
            # NOTE: changing the visibility requires the user to be owner which means they should have DELETE permission
            required_scope = Scope.DELETE
        if patch.namespace is not None and patch.namespace != old_data_connector_parent:
            # NOTE: changing the namespace requires the user to be owner which means they should have DELETE permission # noqa E501
            required_scope = Scope.DELETE
        if patch.slug is not None and patch.slug != old_data_connector.slug:
            # NOTE: changing the slug requires the user to be owner which means they should have DELETE permission
            required_scope = Scope.DELETE
        authorized = await self.authz.has_permission(
            user, ResourceType.data_connector, data_connector_id, required_scope
        )
        if not authorized:
            raise errors.MissingResourceError(message=not_found_msg)

        current_etag = old_data_connector.etag
        if current_etag != etag:
            raise errors.ConflictError(message=f"Current ETag is {current_etag}, not {etag}.")

        if patch.name is not None:
            data_connector.name = patch.name
        if patch.visibility is not None:
            visibility_orm = (
                apispec.Visibility(patch.visibility)
                if isinstance(patch.visibility, str)
                else apispec.Visibility(patch.visibility.value)
            )
            data_connector.visibility = visibility_orm
        if isinstance(old_data_connector, models.DataConnector) and (
            (patch.namespace is not None and patch.namespace != old_data_connector.namespace.path)
            or (patch.slug is not None and patch.slug != old_data_connector.slug)
        ):
            match patch.namespace, patch.slug:
                case (None, new_slug) if new_slug is not None:
                    new_path = old_data_connector.path.parent() / DataConnectorSlug(new_slug)
                case (new_ns, None) if new_ns is not None:
                    new_path = new_ns / DataConnectorSlug(old_data_connector.slug)
                case (new_ns, new_slug) if new_ns is not None and new_slug is not None:
                    new_path = new_ns / DataConnectorSlug(new_slug)
                case _:
                    raise errors.ProgrammingError(
                        message=f"Moving a data connector from {old_data_connector.path.serialize()} "
                        f"to namespace: {patch.namespace} and slug: {patch.slug} is not supported."
                    )
            await self.group_repo.move_data_connector(
                user,
                old_data_connector,
                new_path,
                session,
            )
            if isinstance(new_path, DataConnectorInProjectPath) and old_data_connector.path != new_path:
                # Moving the data connector into a new project means that we should link it too
                project = await self.project_repo.get_project_by_namespace_slug(
                    user,
                    namespace=new_path.first.value,
                    slug=new_path.second,
                )
                link = models.UnsavedDataConnectorToProjectLink(
                    data_connector_id=data_connector_id, project_id=project.id
                )
                with suppress(errors.ConflictError):
                    # If there is a conflict error it means the link already exists so we ignore it
                    await self.insert_link(
                        user,
                        link,
                        session=session,
                    )
        if (
            isinstance(old_data_connector, models.GlobalDataConnector)
            and patch.slug is not None
            and patch.slug != old_data_connector.slug
        ):
            data_connector.global_slug = patch.slug
        if patch.description is not None:
            data_connector.description = patch.description if patch.description else None
        if patch.keywords is not None:
            data_connector.keywords = patch.keywords if patch.keywords else None
        if patch.storage is not None:
            if patch.storage.configuration is not None:
                data_connector.configuration = patch.storage.configuration
                data_connector.storage_type = data_connector.configuration["type"]
            if patch.storage.source_path is not None:
                data_connector.source_path = patch.storage.source_path
            if patch.storage.target_path is not None:
                data_connector.target_path = patch.storage.target_path
            if patch.storage.readonly is not None:
                data_connector.readonly = patch.storage.readonly

        await session.flush()
        await session.refresh(data_connector)

        return models.DataConnectorUpdate(
            old=old_data_connector,
            new=data_connector.dump(),
        )

    @with_db_transaction
    @Authz.authz_change(AuthzOperation.delete, ResourceType.data_connector)
    @update_search_document
    async def delete_data_connector(
        self,
        user: base_models.APIUser,
        data_connector_id: ULID,
        *,
        session: AsyncSession | None = None,
    ) -> models.DeletedDataConnector | None:
        """Delete a data connector."""
        if not session:
            raise errors.ProgrammingError(message="A database session is required.")
        authorized = await self.authz.has_permission(user, ResourceType.data_connector, data_connector_id, Scope.DELETE)
        if not authorized:
            raise errors.MissingResourceError(
                message=f"Data connector with id '{data_connector_id}' does not exist or you do not have access to it."
            )

        result = await session.scalars(
            select(schemas.DataConnectorORM).where(schemas.DataConnectorORM.id == data_connector_id)
        )
        data_connector_orm = result.one_or_none()
        if data_connector_orm is None:
            return None

        await session.delete(data_connector_orm)
        return models.DeletedDataConnector(id=data_connector_id)

    async def get_data_connector_permissions(
        self, user: base_models.APIUser, data_connector_id: ULID
    ) -> models.DataConnectorPermissions:
        """Get the permissions of the user on a given data connector."""
        # Get the data connector first, it will check if the user can view it.
        await self.get_data_connector(user=user, data_connector_id=data_connector_id)

        scopes = [Scope.WRITE, Scope.DELETE, Scope.CHANGE_MEMBERSHIP]
        items = [
            CheckPermissionItem(resource_type=ResourceType.data_connector, resource_id=data_connector_id, scope=scope)
            for scope in scopes
        ]
        responses = await self.authz.has_permissions(user=user, items=items)
        permissions = models.DataConnectorPermissions(write=False, delete=False, change_membership=False)
        for item, has_permission in responses:
            if not has_permission:
                continue
            match item.scope:
                case Scope.WRITE:
                    permissions.write = True
                case Scope.DELETE:
                    permissions.delete = True
                case Scope.CHANGE_MEMBERSHIP:
                    permissions.change_membership = True
        return permissions

    async def get_links_from(
        self, user: base_models.APIUser, data_connector_id: ULID
    ) -> list[models.DataConnectorToProjectLink]:
        """Get links from a given data connector."""
        authorized = await self.authz.has_permission(user, ResourceType.data_connector, data_connector_id, Scope.READ)
        if not authorized:
            raise errors.MissingResourceError(
                message=f"Data connector with id '{data_connector_id}' does not exist or you do not have access to it."
            )

        project_ids = await self.authz.resources_with_permission(user, user.id, ResourceType.project, Scope.READ)

        async with self.session_maker() as session:
            stmt = (
                select(schemas.DataConnectorToProjectLinkORM)
                .where(schemas.DataConnectorToProjectLinkORM.data_connector_id == data_connector_id)
                .where(schemas.DataConnectorToProjectLinkORM.project_id.in_(project_ids))
            )
            result = await session.scalars(stmt)
            links_orm = result.all()
            return [link.dump() for link in links_orm]

    async def get_links_to(
        self, user: base_models.APIUser, project_id: ULID
    ) -> list[models.DataConnectorToProjectLink]:
        """Get links to a given project."""
        authorized = await self.authz.has_permission(user, ResourceType.project, project_id, Scope.READ)
        if not authorized:
            raise errors.MissingResourceError(
                message=f"Project with id '{project_id}' does not exist or you do not have access to it."
            )

        allowed_dcs = await self.authz.resources_with_permission(user, user.id, ResourceType.data_connector, Scope.READ)

        async with self.session_maker() as session:
            stmt = (
                select(schemas.DataConnectorToProjectLinkORM)
                .where(schemas.DataConnectorToProjectLinkORM.project_id == project_id)
                .where(schemas.DataConnectorToProjectLinkORM.data_connector_id.in_(allowed_dcs))
            )
            result = await session.scalars(stmt)
            links_orm = result.all()
            return [link.dump() for link in links_orm]

    async def get_inaccessible_links_to_project(self, user: base_models.APIUser, project_id: ULID) -> Sequence[ULID]:
        """Get data connector link IDs in a project that the user has no access to."""
        authorized = await self.authz.has_permission(user, ResourceType.project, project_id, Scope.READ)
        if not authorized:
            raise errors.MissingResourceError(
                message=f"Project with id '{project_id}' does not exist or you do not have access to it."
            )

        allowed_dcs = await self.authz.resources_with_permission(user, user.id, ResourceType.data_connector, Scope.READ)

        async with self.session_maker() as session:
            stmt = (
                select(schemas.DataConnectorToProjectLinkORM.id)
                .where(schemas.DataConnectorToProjectLinkORM.project_id == project_id)
                .where(schemas.DataConnectorToProjectLinkORM.data_connector_id.not_in(allowed_dcs))
            )
            result = await session.scalars(stmt)
            ulids = result.all()
            return ulids

    @with_db_transaction
    async def insert_link(
        self,
        user: base_models.APIUser,
        link: models.UnsavedDataConnectorToProjectLink,
        *,
        session: AsyncSession | None = None,
    ) -> models.DataConnectorToProjectLink:
        """Insert a new link from a data connector to a project."""
        if not session:
            raise errors.ProgrammingError(message="A database session is required.")

        if user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")

        dc_error_msg = (
            f"Data connector with id '{link.data_connector_id}' does not exist or you do not have access to it."
        )
        allowed_from = await self.authz.has_permission(
            user, ResourceType.data_connector, link.data_connector_id, Scope.READ
        )
        if not allowed_from:
            raise errors.MissingResourceError(message=dc_error_msg)
        allowed_to = await self.authz.has_permission(user, ResourceType.project, link.project_id, Scope.WRITE)
        if not allowed_to:
            raise errors.MissingResourceError(
                message=f"The user with ID {user.id} cannot perform operation {Scope.WRITE} "
                f"on {ResourceType.project.value} "
                f"with ID {link.project_id} or the resource does not exist."
            )

        data_connector = (
            await session.scalars(
                select(schemas.DataConnectorORM).where(schemas.DataConnectorORM.id == link.data_connector_id)
            )
        ).one_or_none()
        if data_connector is None:
            raise errors.MissingResourceError(message=dc_error_msg)

        project = (
            await session.scalars(select(schemas.ProjectORM).where(schemas.ProjectORM.id == link.project_id))
        ).one_or_none()
        if project is None:
            raise errors.MissingResourceError(
                message=f"Project with id '{link.project_id}' does not exist or you do not have access to it."
            )

        existing_link = await session.scalar(
            select(schemas.DataConnectorToProjectLinkORM)
            .where(schemas.DataConnectorToProjectLinkORM.data_connector_id == link.data_connector_id)
            .where(schemas.DataConnectorToProjectLinkORM.project_id == link.project_id)
        )
        if existing_link is not None:
            raise errors.ConflictError(
                message=f"A link from data connector {link.data_connector_id} to project {link.project_id} already exists."  # noqa E501
            )

        link_orm = schemas.DataConnectorToProjectLinkORM(
            data_connector_id=link.data_connector_id,
            project_id=link.project_id,
            created_by_id=user.id,
        )

        session.add(link_orm)
        await session.flush()
        await session.refresh(link_orm)

        return link_orm.dump()

    @with_db_transaction
    async def copy_link(
        self,
        user: base_models.APIUser,
        target_project_id: ULID,
        link: models.DataConnectorToProjectLink,
        *,
        session: AsyncSession | None = None,
    ) -> models.DataConnectorToProjectLink:
        """Create a new link from a given data connector link to a project."""
        allowed_to_read_dc = await self.authz.has_permission(
            user, ResourceType.data_connector, link.data_connector_id, Scope.READ
        )
        allowed_to_write_project = await self.authz.has_permission(
            user, ResourceType.project, target_project_id, Scope.WRITE
        )
        if not allowed_to_read_dc:
            raise errors.MissingResourceError(
                message=f"The data connector with ID {link.data_connector_id} does not exist "
                "or you do not have access to it"
            )
        if not allowed_to_write_project:
            raise errors.MissingResourceError(
                message=f"The project with ID {link.project_id} does not exist or you do not have access to it"
            )
        unsaved_link = models.UnsavedDataConnectorToProjectLink(
            data_connector_id=link.data_connector_id, project_id=target_project_id
        )
        return await self.insert_link(user=user, link=unsaved_link, session=session)

    @with_db_transaction
    @Authz.authz_change(AuthzOperation.delete_link, ResourceType.data_connector)
    async def delete_link(
        self,
        user: base_models.APIUser,
        data_connector_id: ULID,
        link_id: ULID,
        *,
        session: AsyncSession | None = None,
    ) -> models.DataConnectorToProjectLink | None:
        """Delete a link from a data connector to a project."""
        if not session:
            raise errors.ProgrammingError(message="A database session is required.")

        link_orm = (
            await session.scalars(
                select(schemas.DataConnectorToProjectLinkORM)
                .where(schemas.DataConnectorToProjectLinkORM.id == link_id)
                .where(schemas.DataConnectorToProjectLinkORM.data_connector_id == data_connector_id)
            )
        ).one_or_none()
        if link_orm is None:
            return None

        allowed_to_write_project = await self.authz.has_permission(
            user, ResourceType.project, link_orm.project_id, Scope.WRITE
        )
        if not allowed_to_write_project:
            raise errors.MissingResourceError(
                message=f"The project with ID {link_orm.project_id} does not exist or you do not have access to it"
            )

        dc = await self.get_data_connector(user, data_connector_id)
        if isinstance(dc.namespace, ProjectNamespace) and dc.namespace.underlying_resource_id == link_orm.project_id:
            raise errors.ValidationError(
                message="The data connector link to the owner project cannot be removed,"
                " you have to first move the data connector elsewhere and then unlink it."
            )

        link = link_orm.dump()
        await session.delete(link_orm)
        return link


class DataConnectorSecretRepository:
    """Repository for data connector secrets."""

    def __init__(
        self,
        session_maker: Callable[..., AsyncSession],
        data_connector_repo: DataConnectorRepository,
        user_repo: UserRepo,
        secret_service_public_key: rsa.RSAPublicKey,
        authz: Authz,
    ) -> None:
        self.session_maker = session_maker
        self.data_connector_repo = data_connector_repo
        self.user_repo = user_repo
        self.secret_service_public_key = secret_service_public_key
        self.authz = authz

    async def get_data_connectors_with_secrets(
        self,
        user: base_models.APIUser,
        project_id: ULID,
    ) -> AsyncIterator[models.DataConnectorWithSecrets]:
        """Get all data connectors and their secrets for a project."""
        if user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")

        can_read_project = await self.authz.has_permission(user, ResourceType.project, project_id, Scope.READ)
        if not can_read_project:
            raise errors.MissingResourceError(
                message=f"The project ID with {project_id} does not exist or you dont have permission to access it"
            )

        data_connector_ids = await self.authz.resources_with_permission(
            user, user.id, ResourceType.data_connector, Scope.READ
        )

        async with self.session_maker() as session:
            stmt = (
                select(schemas.DataConnectorORM)
                .where(
                    schemas.DataConnectorORM.project_links.any(
                        schemas.DataConnectorToProjectLinkORM.project_id == project_id
                    ),
                    schemas.DataConnectorORM.id.in_(data_connector_ids),
                )
                .options(
                    joinedload(schemas.DataConnectorORM.slug)
                    .joinedload(ns_schemas.EntitySlugORM.project)
                    .joinedload(ProjectORM.slug)
                )
            )

            results = await session.stream_scalars(stmt)
            async for dc in results:
                secrets = await self.get_data_connector_secrets(user, dc.id)
                yield models.DataConnectorWithSecrets(dc.dump(), secrets)

    async def get_data_connector_secrets(
        self,
        user: base_models.APIUser,
        data_connector_id: ULID,
    ) -> list[models.DataConnectorSecret]:
        """Get data connectors secrets from the database."""
        if user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")

        async with self.session_maker() as session:
            stmt = (
                select(schemas.DataConnectorSecretORM)
                .join(schemas.DataConnectorSecretORM.secret)
                .where(
                    or_(
                        schemas.SecretORM.expiration_timestamp.is_(None),
                        schemas.SecretORM.expiration_timestamp > datetime.now(UTC) + timedelta(seconds=120),
                    )
                )
                .where(schemas.DataConnectorSecretORM.user_id == user.id)
                .where(schemas.DataConnectorSecretORM.data_connector_id == data_connector_id)
                .where(schemas.DataConnectorSecretORM.secret_id == secrets_schemas.SecretORM.id)
                .where(secrets_schemas.SecretORM.user_id == user.id)
            )
            results = await session.scalars(stmt)
            secrets = results.all()

            return [secret.dump() for secret in secrets]

    async def patch_data_connector_secrets(
        self,
        user: base_models.APIUser,
        data_connector_id: ULID,
        secrets: list[models.DataConnectorSecretUpdate],
        expiration_timestamp: datetime | None,
    ) -> list[models.DataConnectorSecret]:
        """Create, update or remove data connector secrets."""
        if user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")

        # NOTE: check that the user can access the data connector
        data_connector = await self.data_connector_repo.get_data_connector(
            user=user, data_connector_id=data_connector_id
        )

        secrets_as_dict = {s.name: s.value for s in secrets}

        async with self.session_maker() as session, session.begin():
            stmt = (
                select(schemas.DataConnectorSecretORM)
                .where(schemas.DataConnectorSecretORM.user_id == user.id)
                .where(schemas.DataConnectorSecretORM.data_connector_id == data_connector_id)
                .where(schemas.DataConnectorSecretORM.secret_id == secrets_schemas.SecretORM.id)
                .where(secrets_schemas.SecretORM.user_id == user.id)
            )
            result = await session.scalars(stmt)
            existing_secrets = result.all()
            existing_secrets_as_dict = {s.name: s for s in existing_secrets}

            all_secrets = []

            for name, value in secrets_as_dict.items():
                if value is None:
                    # Remove the secret
                    data_connector_secret_orm = existing_secrets_as_dict.get(name)
                    if data_connector_secret_orm is None:
                        continue
                    await session.execute(
                        delete(secrets_schemas.SecretORM).where(
                            secrets_schemas.SecretORM.id == data_connector_secret_orm.secret_id
                        )
                    )
                    del existing_secrets_as_dict[name]
                    continue

                encrypted_value, encrypted_key = await self.user_repo.encrypt_user_secret(
                    requested_by=user,
                    secret_service_public_key=self.secret_service_public_key,
                    secret_value=value,
                )

                if data_connector_secret_orm := existing_secrets_as_dict.get(name):
                    data_connector_secret_orm.secret.update(
                        encrypted_value=encrypted_value,
                        encrypted_key=encrypted_key,
                        expiration_timestamp=expiration_timestamp,
                    )
                else:
                    secret_name = f"{data_connector.name[:45]} - {name[:45]}"
                    suffix = "".join([random.choice(string.ascii_lowercase + string.digits) for _ in range(8)])  # nosec B311
                    secret_name_slug = base_models.Slug.from_name(name).value
                    default_filename = f"{secret_name_slug[:200]}-{suffix}"
                    secret_orm = secrets_schemas.SecretORM(
                        name=secret_name,
                        default_filename=default_filename,
                        user_id=user.id,
                        encrypted_value=encrypted_value,
                        encrypted_key=encrypted_key,
                        kind=SecretKind.storage,
                        expiration_timestamp=expiration_timestamp,
                    )
                    data_connector_secret_orm = schemas.DataConnectorSecretORM(
                        name=name,
                        user_id=user.id,
                        data_connector_id=data_connector_id,
                        secret_id=secret_orm.id,
                    )
                    session.add(secret_orm)
                    session.add(data_connector_secret_orm)
                    await session.flush()
                    await session.refresh(data_connector_secret_orm)

                all_secrets.append(data_connector_secret_orm.dump())

            return all_secrets

    async def delete_data_connector_secrets(self, user: base_models.APIUser, data_connector_id: ULID) -> None:
        """Delete data connector secrets."""
        if user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")

        async with self.session_maker() as session, session.begin():
            stmt = (
                delete(secrets_schemas.SecretORM)
                .where(secrets_schemas.SecretORM.user_id == user.id)
                .where(secrets_schemas.SecretORM.id == schemas.DataConnectorSecretORM.secret_id)
                .where(schemas.DataConnectorSecretORM.data_connector_id == data_connector_id)
            )
            await session.execute(stmt)


_T = TypeVar("_T", int, schemas.DataConnectorORM)


def _filter_by_namespace_slug(stmt: Select[tuple[_T]], namespace: ProjectPath | NamespacePath) -> Select[tuple[_T]]:
    """Filters a select query on data connectors to a given namespace."""
    stmt = stmt.where(
        schemas.DataConnectorORM.slug.has(
            ns_schemas.EntitySlugORM.namespace.has(
                ns_schemas.NamespaceORM.slug == namespace.first.value.lower(),
            )
        )
    )
    if isinstance(namespace, ProjectPath):
        stmt = stmt.where(
            schemas.DataConnectorORM.slug.has(
                ns_schemas.EntitySlugORM.project.has(
                    schemas.ProjectORM.slug.has(
                        ns_schemas.EntitySlugORM.slug == namespace.second.value.lower(),
                    )
                )
            )
        )
    return stmt


def _old_data_connector_slug_queries(
    path: DataConnectorInProjectPath | DataConnectorPath,
) -> list[Select[tuple[schemas.DataConnectorORM]]]:
    """Prepare queries that return data connector IDs based on a full data connector path."""

    def _dc_old_ns_is(slug: NamespaceSlug) -> ColumnExpressionArgument[bool]:
        return schemas.DataConnectorORM.slug.has(
            ns_schemas.EntitySlugORM.namespace.has(
                ns_schemas.NamespaceORM.old_namespaces.any(
                    ns_schemas.NamespaceOldORM.slug == slug.value.lower(),
                )
            )
        )

    def _dc_new_ns_is(slug: NamespaceSlug) -> ColumnExpressionArgument[bool]:
        return schemas.DataConnectorORM.slug.has(
            ns_schemas.EntitySlugORM.namespace.has(
                ns_schemas.NamespaceORM.slug == slug.value.lower(),
            )
        )

    def _dc_old_prj_is(slug: ProjectSlug) -> ColumnExpressionArgument[bool]:
        return schemas.DataConnectorORM.slug.has(
            ns_schemas.EntitySlugORM.project.has(
                ProjectORM.old_slugs.any(
                    ns_schemas.EntitySlugOldORM.slug == slug.value.lower(),
                )
            )
        )

    def _dc_new_prj_is(slug: ProjectSlug) -> ColumnExpressionArgument[bool]:
        return schemas.DataConnectorORM.slug.has(
            ns_schemas.EntitySlugORM.project.has(
                ProjectORM.slug.has(
                    ns_schemas.EntitySlugORM.slug == slug.value.lower(),
                )
            )
        )

    def _dc_old_slug_is(slug: DataConnectorSlug) -> ColumnExpressionArgument[bool]:
        return schemas.DataConnectorORM.old_slugs.any(
            ns_schemas.EntitySlugOldORM.slug == slug.value.lower(),
        )

    def _dc_new_slug_is(slug: DataConnectorSlug) -> ColumnExpressionArgument[bool]:
        return schemas.DataConnectorORM.slug.has(
            ns_schemas.EntitySlugORM.slug == slug.value.lower(),
        )

    def _dc_in_project(path: DataConnectorInProjectPath) -> list[Select[tuple[schemas.DataConnectorORM]]]:
        """This finds all combinations of old/new slugs for user/group, project and data connector.

        It excludes the combination of new/new/new.
        """
        result = []
        for i in range(2**3 - 1):
            # NOTE: Changing the order of the statements here can lead to unexpected
            # consequences or cause combinations that we want to exclude to be added (i.e. new/new/new).
            stmt = select(schemas.DataConnectorORM)
            if i & 0b001 == 0b001:  # noqa: SIM108
                stmt = stmt.where(_dc_new_ns_is(path.first))
            else:
                stmt = stmt.where(_dc_old_ns_is(path.first))

            if i & 0b010 == 0b010:  # noqa: SIM108
                stmt = stmt.where(_dc_new_prj_is(path.second))
            else:
                stmt = stmt.where(_dc_old_prj_is(path.second))

            if i & 0b100 == 0b100:  # noqa: SIM108
                stmt = stmt.where(_dc_new_slug_is(path.third))
            else:
                stmt = stmt.where(_dc_old_slug_is(path.third))
            result.append(stmt)
        return result

    def _dc_in_user_or_group(path: DataConnectorPath) -> list[Select[tuple[schemas.DataConnectorORM]]]:
        old_ns_old_slug = (
            select(schemas.DataConnectorORM).where(_dc_old_ns_is(path.first)).where(_dc_old_slug_is(path.second))
        )
        new_ns_old_slug = (
            select(schemas.DataConnectorORM).where(_dc_new_ns_is(path.first)).where(_dc_old_slug_is(path.second))
        )
        old_ns_new_slug = (
            select(schemas.DataConnectorORM).where(_dc_old_ns_is(path.first)).where(_dc_new_slug_is(path.second))
        )
        return [
            old_ns_old_slug,
            new_ns_old_slug,
            old_ns_new_slug,
        ]

    match path:
        case DataConnectorPath():
            return _dc_in_user_or_group(path)
        case DataConnectorInProjectPath():
            return _dc_in_project(path)
        case _:
            raise errors.ProgrammingError(message="Got unknown data connector path type when resolving slugs.")
