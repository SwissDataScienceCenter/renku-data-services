"""SQLAlchemy schemas for the data connectors database."""

from __future__ import annotations

from datetime import datetime
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, MetaData, String, func, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column, relationship
from sqlalchemy.schema import Index, UniqueConstraint
from ulid import ULID

from renku_data_services.authz import models as authz_models
from renku_data_services.base_orm.registry import COMMON_ORM_REGISTRY
from renku_data_services.crc.orm import ClusterORM
from renku_data_services.data_connectors import models
from renku_data_services.data_connectors.apispec import Visibility
from renku_data_services.data_connectors.doi.models import DOI
from renku_data_services.k8s.constants import ClusterId
from renku_data_services.project.orm import ProjectORM
from renku_data_services.secrets.orm import SecretORM
from renku_data_services.users.orm import UserORM
from renku_data_services.utils.sqlalchemy import ULIDType

if TYPE_CHECKING:
    from renku_data_services.namespace.orm import EntitySlugOldORM, EntitySlugORM

JSONVariant = JSON().with_variant(JSONB(), "postgresql")


class BaseORM(MappedAsDataclass, DeclarativeBase):
    """Base class for all ORM classes."""

    metadata = MetaData(schema="storage")
    registry = COMMON_ORM_REGISTRY


class DataConnectorORM(BaseORM):
    """A data connector for Renku 2.0."""

    __tablename__ = "data_connectors"

    id: Mapped[ULID] = mapped_column("id", ULIDType, primary_key=True, default_factory=lambda: str(ULID()), init=False)
    """ID of this data connector."""

    name: Mapped[str] = mapped_column("name", String(99))
    """Name of the data connector."""

    visibility: Mapped[Visibility]
    """Visibility of the data connector."""

    storage_type: Mapped[str] = mapped_column("storage_type", String(20))
    """Type of storage (e.g. s3), read-only based on 'configuration'."""

    configuration: Mapped[dict[str, Any]] = mapped_column("configuration", JSONVariant)
    """RClone configuration dict."""

    source_path: Mapped[str] = mapped_column("source_path", String())
    """Source path to mount from (e.g. bucket/folder for s3)."""

    target_path: Mapped[str] = mapped_column("target_path", String())
    """Target folder in the repository to mount to."""

    created_by_id: Mapped[str] = mapped_column(ForeignKey(UserORM.keycloak_id), index=True, nullable=False)
    """User ID of the creator of the data connector."""

    description: Mapped[str | None] = mapped_column("description", String(500))
    """Human-readable description of the data connector."""

    keywords: Mapped[list[str] | None] = mapped_column("keywords", ARRAY(String(99)), nullable=True)
    """Keywords for the data connector."""

    slug: Mapped[EntitySlugORM | None] = relationship(
        lazy="joined", init=False, repr=False, viewonly=True, back_populates="data_connector"
    )
    """Slug of the data connector."""

    global_slug: Mapped[str | None] = mapped_column(String(99), index=True, nullable=True, default=None, unique=True)
    """Slug for global data connectors."""

    readonly: Mapped[bool] = mapped_column("readonly", Boolean(), default=True)
    """Whether this storage should be mounted readonly or not """

    creation_date: Mapped[datetime] = mapped_column(
        "creation_date", DateTime(timezone=True), default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        "updated_at",
        DateTime(timezone=True),
        default=None,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    project_links: Mapped[list[DataConnectorToProjectLinkORM]] = relationship(init=False, viewonly=True)

    old_slugs: Mapped[list[EntitySlugOldORM]] = relationship(
        back_populates="data_connector",
        default_factory=list,
        repr=False,
        init=False,
        viewonly=True,
    )
    doi: Mapped[str | None] = mapped_column(default=None, server_default=None, index=True, nullable=True)
    publisher_name: Mapped[str | None] = mapped_column(default=None, server_default=None, index=True, nullable=True)
    publisher_url: Mapped[str | None] = mapped_column(default=None, server_default=None, index=True, nullable=True)

    def dump(self) -> models.DataConnector | models.GlobalDataConnector:
        """Create a data connector model from the DataConnectorORM."""
        if self.global_slug:
            return models.GlobalDataConnector(
                id=self.id,
                name=self.name,
                slug=self.global_slug,
                visibility=self._dump_visibility(),
                created_by=self.created_by_id,  # TODO: should we use an admin id? Or drop it?
                creation_date=self.creation_date,
                updated_at=self.updated_at,
                storage=self._dump_storage(),
                description=self.description,
                keywords=self.keywords,
                publisher_name=self.publisher_name,
                publisher_url=self.publisher_url,
                doi=DOI(self.doi) if self.doi is not None else None,
            )

        elif self.slug is None:
            raise ValueError("Either the slug or the global slug must be set.")

        return models.DataConnector(
            id=self.id,
            name=self.name,
            slug=self.slug.slug,
            namespace=self.slug.dump_namespace(),
            visibility=self._dump_visibility(),
            created_by=self.created_by_id,
            creation_date=self.creation_date,
            updated_at=self.updated_at,
            storage=self._dump_storage(),
            description=self.description,
            keywords=self.keywords,
        )

    def _dump_visibility(self) -> authz_models.Visibility:
        return (
            authz_models.Visibility.PUBLIC if self.visibility == Visibility.public else authz_models.Visibility.PRIVATE
        )

    def _dump_storage(self) -> models.CloudStorageCore:
        return models.CloudStorageCore(
            storage_type=self.storage_type,
            configuration=self.configuration,
            source_path=self.source_path,
            target_path=self.target_path,
            readonly=self.readonly,
        )


class DataConnectorToProjectLinkORM(BaseORM):
    """A link from a data connector to a project in Renku 2.0."""

    __tablename__ = "data_connector_to_project_links"
    __table_args__ = (
        UniqueConstraint(
            "data_connector_id",
            "project_id",
            name="_unique_data_connector_id_project_id_uc",
        ),
    )

    id: Mapped[ULID] = mapped_column("id", ULIDType, primary_key=True, default_factory=lambda: str(ULID()), init=False)
    """ID of this data connector to project link."""

    data_connector_id: Mapped[ULID] = mapped_column(
        ForeignKey(DataConnectorORM.id, ondelete="CASCADE"), index=True, nullable=False
    )
    """ID of the data connector."""

    project_id: Mapped[ULID] = mapped_column(ForeignKey(ProjectORM.id, ondelete="CASCADE"), index=True, nullable=False)
    """ID of the project."""

    created_by_id: Mapped[str] = mapped_column(
        ForeignKey(UserORM.keycloak_id, ondelete="CASCADE"), index=True, nullable=False
    )
    """User ID of the creator of the data connector."""

    creation_date: Mapped[datetime] = mapped_column(
        "creation_date", DateTime(timezone=True), default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        "updated_at",
        DateTime(timezone=True),
        default=None,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def dump(self) -> models.DataConnectorToProjectLink:
        """Create a link model from the DataConnectorProjectLinkORM."""
        return models.DataConnectorToProjectLink(
            id=self.id,
            data_connector_id=self.data_connector_id,
            project_id=self.project_id,
            created_by=self.created_by_id,
            creation_date=self.creation_date,
            updated_at=self.updated_at,
        )


class DataConnectorSecretORM(BaseORM):
    """Secrets for data connectors."""

    __tablename__ = "data_connector_secrets"
    __table_args__ = (
        Index("ix_storage_data_connector_secrets_user_id_data_connector_id", "user_id", "data_connector_id"),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey(UserORM.keycloak_id, ondelete="CASCADE"), primary_key=True)

    data_connector_id: Mapped[ULID] = mapped_column(
        ForeignKey(DataConnectorORM.id, ondelete="CASCADE"), primary_key=True
    )

    name: Mapped[str] = mapped_column("name", String(), primary_key=True)

    secret_id: Mapped[ULID] = mapped_column("secret_id", ForeignKey(SecretORM.id, ondelete="CASCADE"))
    secret: Mapped[SecretORM] = relationship(
        init=False, repr=False, back_populates="data_connector_secrets", lazy="selectin"
    )

    def dump(self) -> models.DataConnectorSecret:
        """Create a data connector secret model from the DataConnectorSecretORM."""
        return models.DataConnectorSecret(
            name=self.name,
            user_id=self.user_id,
            data_connector_id=self.data_connector_id,
            secret_id=self.secret_id,
        )


class DepositStatusORM(BaseORM):
    """Deposit statuses."""

    __tablename__ = "deposit_statuses"

    id: Mapped[ULID] = mapped_column(
        "id", ULIDType, primary_key=True, server_default=text("generate_ulid()"), init=False
    )
    status: Mapped[str] = mapped_column("status", String(100), unique=True, index=True)

    def dump(self) -> models.DepositStatus:
        """Convert to a model status."""
        try:
            return models.DepositStatus(self.status.lower())
        except ValueError:
            return models.DepositStatus.unknown


class DepositSourceORM(BaseORM):
    """Deposit sources, like Zenodo for example."""

    __tablename__ = "deposit_sources"

    id: Mapped[ULID] = mapped_column(
        "id", ULIDType, primary_key=True, server_default=text("generate_ulid()"), init=False
    )
    source: Mapped[str] = mapped_column("source", String(100), unique=True, index=True)

    def dump(self) -> models.DepositSource:
        """Convert to a model source."""
        try:
            return models.DepositSource(self.source.lower())
        except ValueError:
            return models.DepositSource.unknown


class DepositORM(BaseORM):
    """The record of a data deposit connected with a data provider (like Zenodo)."""

    __tablename__ = "deposits"

    id: Mapped[ULID] = mapped_column(
        "id", ULIDType, primary_key=True, server_default=text("generate_ulid()"), init=False
    )
    source_id: Mapped[ULID] = mapped_column(
        "source_id", ForeignKey(DepositSourceORM.id, ondelete="CASCADE"), index=True
    )
    source: Mapped[DepositSourceORM] = relationship(
        init=False, repr=False, back_populates="deposit_sources", lazy="selectin"
    )
    status_id: Mapped[ULID] = mapped_column(
        "status_id", ForeignKey(DepositStatusORM.id, ondelete="CASCADE"), index=True
    )
    status: Mapped[DepositStatusORM] = relationship(
        init=False, repr=False, back_populates="deposit_statuses", lazy="selectin"
    )
    original_id: Mapped[str]
    data_connector_id: Mapped[ULID] = mapped_column(
        "data_connector_id", ForeignKey(DataConnectorORM.id, ondelete="CASCADE"), index=True
    )
    data_connector: Mapped[DataConnectorORM] = relationship(
        init=False, repr=False, back_populates="data_connectors", lazy="selectin"
    )
    user_id: Mapped[str] = mapped_column(ForeignKey(UserORM.keycloak_id, ondelete="CASCADE"), primary_key=True)
    path: Mapped[str | None]
    job_name: Mapped[str]
    name: Mapped[str]
    cluster_id: Mapped[ULID] = mapped_column("cluster_id", ForeignKey(ClusterORM.id, ondelete="CASCADE"), index=True)

    def dump(self) -> models.DepositJob:
        """Create a deposit model from the ORM."""
        return models.DepositJob(
            name=self.job_name,
            cluster_id=ClusterId(self.cluster_id),
            deposit=models.Deposit(
                name=self.name,
                data_connector_id=self.data_connector_id,
                original_id=self.original_id,
                source=self.source.dump(),
                path=PurePosixPath(self.path) if self.path else None,
                status=self.status.dump(),
                id=self.id,
            ),
        )
