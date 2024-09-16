"""Adapters for data connectors database classes."""

from collections.abc import Callable
from typing import TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from renku_data_services import base_models, errors
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
    ) -> None:
        self.session_maker = session_maker

    async def get_data_connectors(
        self, pagination: PaginationRequest, namespace: str | None = None
    ) -> tuple[list[models.DataConnector], int]:
        """Get multiple data connectors from the database."""
        async with self.session_maker() as session:
            stmt = select(schemas.DataConnectorORM)
            if namespace:
                stmt = _filter_by_namespace_slug(stmt, namespace)
            stmt = stmt.limit(pagination.per_page).offset(pagination.offset)
            stmt = stmt.order_by(schemas.DataConnectorORM.id.desc())
            stmt_count = select(func.count()).select_from(schemas.DataConnectorORM)
            if namespace:
                stmt_count = _filter_by_namespace_slug(stmt_count, namespace)
            results = await session.scalars(stmt), await session.scalar(stmt_count)
            data_connectors = results[0].all()
            total_elements = results[1] or 0
            return [dc.dump() for dc in data_connectors], total_elements

    async def get_data_connector(
        self,
        data_connector_id: ULID,
    ) -> models.DataConnector:
        """Get one data connector from the database."""
        async with self.session_maker() as session:
            result = await session.scalars(
                select(schemas.DataConnectorORM).where(schemas.DataConnectorORM.id == data_connector_id)
            )
            data_connector = result.one_or_none()
            if data_connector is None:
                raise errors.MissingResourceError(
                    message=f"Data connector with id '{data_connector_id}' does not exist or you do not have access to it."  # noqa: E501
                )
            return data_connector.dump()

    async def get_data_connector_by_slug(self, namespace: str, slug: str) -> models.DataConnector:
        """Get one data connector from the database by slug."""
        async with self.session_maker() as session:
            stmt = select(schemas.DataConnectorORM)
            stmt = _filter_by_namespace_slug(stmt, namespace)
            stmt = stmt.where(ns_schemas.EntitySlugORM.slug == slug.lower())
            result = await session.scalars(stmt)
            data_connector = result.one_or_none()
            if data_connector is None:
                raise errors.MissingResourceError(
                    message=f"Data connector with identifier '{namespace}/{slug}' does not exist or you do not have access to it."  # noqa: E501
                )
            return data_connector.dump()

    @with_db_transaction
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
    async def update_data_connector(
        self,
        data_connector_id: ULID,
        patch: models.DataConnectorPatch,
        etag: str,
        *,
        session: AsyncSession | None = None,
    ) -> models.DataConnector:
        """Update a data connector entry."""
        if not session:
            raise errors.ProgrammingError(message="A database session is required.")
        result = await session.scalars(
            select(schemas.DataConnectorORM).where(schemas.DataConnectorORM.id == data_connector_id)
        )
        data_connector = result.one_or_none()
        if data_connector is None:
            raise errors.MissingResourceError(
                message=f"Data connector with id '{data_connector_id}' does not exist or you do not have access to it."
            )

        current_etag = data_connector.dump().etag
        if current_etag != etag:
            raise errors.ConflictError(message=f"Current ETag is {current_etag}, not {etag}.")

        # TODO: handle namespace or slug update
        if patch.name is not None:
            data_connector.name = patch.name
        if patch.visibility is not None:
            visibility_orm = (
                apispec.Visibility(patch.visibility)
                if isinstance(patch.visibility, str)
                else apispec.Visibility(patch.visibility.value)
            )
            data_connector.visibility = visibility_orm
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

        return data_connector.dump()

    @with_db_transaction
    async def delete_data_connector(
        self,
        data_connector_id: ULID,
        *,
        session: AsyncSession | None = None,
    ) -> models.DataConnector | None:
        """Delete a data connector."""
        if not session:
            raise errors.ProgrammingError(message="A database session is required.")
        result = await session.scalars(
            select(schemas.DataConnectorORM).where(schemas.DataConnectorORM.id == data_connector_id)
        )
        data_connector = result.one_or_none()
        if data_connector is None:
            return None

        await session.delete(data_connector)

        return data_connector.dump()


_T = TypeVar("_T")


def _filter_by_namespace_slug(statement: Select[tuple[_T]], namespace: str) -> Select[tuple[_T]]:
    """Filters a select query on data connectors to a given namespace."""
    return (
        statement.where(ns_schemas.NamespaceORM.slug == namespace.lower())
        .where(ns_schemas.EntitySlugORM.namespace_id == ns_schemas.NamespaceORM.id)
        .where(schemas.DataConnectorORM.id == ns_schemas.EntitySlugORM.data_connector_id)
    )
