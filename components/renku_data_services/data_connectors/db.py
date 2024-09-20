"""Adapters for data connectors database classes."""

from collections.abc import Callable
from typing import TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from renku_data_services import base_models, errors
from renku_data_services.authz.authz import Authz, AuthzOperation, ResourceType
from renku_data_services.authz.models import Scope
from renku_data_services.base_api.pagination import PaginationRequest
from renku_data_services.data_connectors import apispec, models
from renku_data_services.data_connectors import orm as schemas
from renku_data_services.namespace import orm as ns_schemas
from renku_data_services.utils.core import with_db_transaction


class DataConnectorRepository:
    """Repository for data connectors."""

    def __init__(
        self,
        session_maker: Callable[..., AsyncSession],
        authz: Authz,
    ) -> None:
        self.session_maker = session_maker
        self.authz = authz

    async def get_data_connectors(
        self, user: base_models.APIUser, pagination: PaginationRequest, namespace: str | None = None
    ) -> tuple[list[models.DataConnector], int]:
        """Get multiple data connectors from the database."""
        data_connector_ids = await self.authz.resources_with_permission(
            user, user.id, ResourceType.data_connector, Scope.READ
        )

        async with self.session_maker() as session:
            stmt = select(schemas.DataConnectorORM).where(schemas.DataConnectorORM.id.in_(data_connector_ids))
            if namespace:
                stmt = _filter_by_namespace_slug(stmt, namespace)
            stmt = stmt.limit(pagination.per_page).offset(pagination.offset)
            stmt = stmt.order_by(schemas.DataConnectorORM.id.desc())
            stmt_count = (
                select(func.count())
                .select_from(schemas.DataConnectorORM)
                .where(schemas.DataConnectorORM.id.in_(data_connector_ids))
            )
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
    ) -> models.DataConnector:
        """Get one data connector from the database."""
        not_found_msg = f"Data connector with id '{
            data_connector_id}' does not exist or you do not have access to it."

        authorized = await self.authz.has_permission(user, ResourceType.data_connector, data_connector_id, Scope.READ)
        if not authorized:
            raise errors.MissingResourceError(message=not_found_msg)

        async with self.session_maker() as session:
            result = await session.scalars(
                select(schemas.DataConnectorORM).where(schemas.DataConnectorORM.id == data_connector_id)
            )
            data_connector = result.one_or_none()
            if data_connector is None:
                raise errors.MissingResourceError(message=not_found_msg)
            return data_connector.dump()

    async def get_data_connector_by_slug(
        self, user: base_models.APIUser, namespace: str, slug: str
    ) -> models.DataConnector:
        """Get one data connector from the database by slug."""
        not_found_msg = f"Data connector with identifier '{
                namespace}/{slug}' does not exist or you do not have access to it."

        async with self.session_maker() as session:
            stmt = select(schemas.DataConnectorORM)
            stmt = _filter_by_namespace_slug(stmt, namespace)
            stmt = stmt.where(ns_schemas.EntitySlugORM.slug == slug.lower())
            result = await session.scalars(stmt)
            data_connector = result.one_or_none()
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
    async def insert_data_connector(
        self,
        user: base_models.APIUser,
        data_connector: models.UnsavedDataConnector,
        *,
        session: AsyncSession | None = None,
    ) -> models.DataConnector:
        """Insert a new data connector entry."""
        if not session:
            raise errors.ProgrammingError(message="A database session is required.")
        ns = await session.scalar(
            select(ns_schemas.NamespaceORM).where(ns_schemas.NamespaceORM.slug == data_connector.namespace.lower())
        )
        if not ns:
            raise errors.MissingResourceError(
                message=f"The data connector cannot be created because the namespace {
                    data_connector.namespace} does not exist."
            )
        if not ns.group_id and not ns.user_id:
            raise errors.ProgrammingError(message="Found a namespace that has no group or user associated with it.")

        if user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")

        resource_type, resource_id = (
            (ResourceType.group, ns.group_id) if ns.group and ns.group_id else (ResourceType.user_namespace, ns.id)
        )
        has_permission = await self.authz.has_permission(user, resource_type, resource_id, Scope.WRITE)
        if not has_permission:
            raise errors.ForbiddenError(
                message=f"The data connector cannot be created because you do not have sufficient permissions with the namespace {data_connector.namespace}"  # noqa: E501
            )

        slug = data_connector.slug or base_models.Slug.from_name(data_connector.name).value

        existing_slug = await session.scalar(
            select(ns_schemas.EntitySlugORM)
            .where(ns_schemas.EntitySlugORM.namespace_id == ns.id)
            .where(ns_schemas.EntitySlugORM.slug == slug)
        )
        if existing_slug is not None:
            raise errors.ConflictError(message=f"An entity with the slug '{ns.slug}/{slug}' already exists.")

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
        )
        data_connector_slug = ns_schemas.EntitySlugORM.create_data_connector_slug(
            slug, data_connector_id=data_connector_orm.id, namespace_id=ns.id
        )

        session.add(data_connector_orm)
        session.add(data_connector_slug)
        await session.flush()
        await session.refresh(data_connector_orm)

        return data_connector_orm.dump()

    @with_db_transaction
    @Authz.authz_change(AuthzOperation.update, ResourceType.data_connector)
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
            select(schemas.DataConnectorORM).where(schemas.DataConnectorORM.id == data_connector_id)
        )
        data_connector = result.one_or_none()
        if data_connector is None:
            raise errors.MissingResourceError(message=not_found_msg)
        old_data_connector = data_connector.dump()

        required_scope = Scope.WRITE
        if patch.visibility is not None and patch.visibility != old_data_connector.visibility:
            # NOTE: changing the visibility requires the user to be owner which means they should have DELETE permission
            required_scope = Scope.DELETE
        if patch.namespace is not None and patch.namespace != old_data_connector.namespace.slug:
            # NOTE: changing the namespace requires the user to be owner which means they should have DELETE permission # noqa E501
            required_scope = Scope.DELETE
        authorized = await self.authz.has_permission(
            user, ResourceType.data_connector, data_connector_id, required_scope
        )
        if not authorized:
            raise errors.MissingResourceError(message=not_found_msg)

        current_etag = data_connector.dump().etag
        if current_etag != etag:
            raise errors.ConflictError(
                message=f"Current ETag is {
                                       current_etag}, not {etag}."
            )

        # TODO: handle slug update
        if patch.name is not None:
            data_connector.name = patch.name
        if patch.visibility is not None:
            visibility_orm = (
                apispec.Visibility(patch.visibility)
                if isinstance(patch.visibility, str)
                else apispec.Visibility(patch.visibility.value)
            )
            data_connector.visibility = visibility_orm
        if patch.namespace is not None:
            ns = await session.scalar(
                select(ns_schemas.NamespaceORM).where(ns_schemas.NamespaceORM.slug == patch.namespace.lower())
            )
            if not ns:
                raise errors.MissingResourceError(
                    message=f"Rhe namespace with slug {
                                                  patch.namespace} does not exist."
                )
            if not ns.group_id and not ns.user_id:
                raise errors.ProgrammingError(message="Found a namespace that has no group or user associated with it.")
            resource_type, resource_id = (
                (ResourceType.group, ns.group_id) if ns.group and ns.group_id else (ResourceType.user_namespace, ns.id)
            )
            has_permission = await self.authz.has_permission(user, resource_type, resource_id, Scope.WRITE)
            if not has_permission:
                raise errors.ForbiddenError(
                    message=f"The data connector cannot be moved because you do not have sufficient permissions with the namespace {patch.namespace}."  # noqa: E501
                )
            data_connector.slug.namespace_id = ns.id
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
    async def delete_data_connector(
        self,
        user: base_models.APIUser,
        data_connector_id: ULID,
        *,
        session: AsyncSession | None = None,
    ) -> models.DataConnector | None:
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

        data_connector = data_connector_orm.dump()
        await session.delete(data_connector_orm)
        return data_connector


class DataConnectorProjectLinkRepository:
    """Repository for links from data connectors to projects."""

    def __init__(
        self,
        session_maker: Callable[..., AsyncSession],
        authz: Authz,
    ) -> None:
        self.session_maker = session_maker
        self.authz = authz

    async def get_links_from(
        self, user: base_models.APIUser, data_connector_id: ULID
    ) -> list[models.DataConnectorToProjectLink]:
        """Get links from a given data connector."""
        authorized = await self.authz.has_permission(user, ResourceType.data_connector, data_connector_id, Scope.READ)
        if not authorized:
            raise errors.MissingResourceError(
                message=f"Data connector with id '{
                    data_connector_id}' does not exist or you do not have access to it."
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
                message=f"Project with id '{
                    project_id}' does not exist or you do not have access to it."
            )

        data_connector_ids = await self.authz.resources_with_permission(
            user, user.id, ResourceType.data_connector, Scope.READ
        )

        async with self.session_maker() as session:
            stmt = (
                select(schemas.DataConnectorToProjectLinkORM)
                .where(schemas.DataConnectorToProjectLinkORM.project_id == project_id)
                .where(schemas.DataConnectorToProjectLinkORM.data_connector_id.in_(data_connector_ids))
            )
            result = await session.scalars(stmt)
            links_orm = result.all()
            return [link.dump() for link in links_orm]

    @with_db_transaction
    @Authz.authz_change(AuthzOperation.create_link, ResourceType.data_connector)
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

        data_connector = (
            await session.scalars(
                select(schemas.DataConnectorORM).where(schemas.DataConnectorORM.id == link.data_connector_id)
            )
        ).one_or_none()
        if data_connector is None:
            raise errors.MissingResourceError(
                message=f"Data connector with id '{link.data_connector_id}' does not exist or you do not have access to it."  # noqa E501
            )

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

        authorized_from = await self.authz.has_permission(
            user, ResourceType.data_connector, data_connector_id, Scope.DELETE
        )
        authorized_to = await self.authz.has_permission(user, ResourceType.project, link_orm.project_id, Scope.WRITE)
        authorized = authorized_from or authorized_to
        if not authorized:
            raise errors.MissingResourceError(
                message=f"Data connector to project link '{link_id}' does not exist or you do not have access to it."
            )

        link = link_orm.dump()
        await session.delete(link_orm)
        return link


_T = TypeVar("_T")


def _filter_by_namespace_slug(statement: Select[tuple[_T]], namespace: str) -> Select[tuple[_T]]:
    """Filters a select query on data connectors to a given namespace."""
    return (
        statement.where(ns_schemas.NamespaceORM.slug == namespace.lower())
        .where(ns_schemas.EntitySlugORM.namespace_id == ns_schemas.NamespaceORM.id)
        .where(schemas.DataConnectorORM.id == ns_schemas.EntitySlugORM.data_connector_id)
    )
