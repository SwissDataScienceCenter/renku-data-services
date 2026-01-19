"""SQLAlchemy schemas for the data connectors database."""

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, MetaData, String, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column, relationship
from sqlalchemy.schema import Index, UniqueConstraint
from ulid import ULID

from renku_data_services.authz import models as authz_models
from renku_data_services.base_orm.registry import COMMON_ORM_REGISTRY
from renku_data_services.data_connectors import models
from renku_data_services.data_connectors.apispec import Visibility
from renku_data_services.data_connectors.doi.models import DOI
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

    slug: Mapped["EntitySlugORM | None"] = relationship(
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
    project_links: Mapped[list["DataConnectorToProjectLinkORM"]] = relationship(init=False, viewonly=True)

    old_slugs: Mapped[list["EntitySlugOldORM"]] = relationship(
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

    project: Mapped["ProjectORM"] = relationship(init=False, repr=False, viewonly=True, lazy="joined")
    """The project this link points to."""

    def dump(self) -> models.DataConnectorToProjectLink:
        """Create a link model from the DataConnectorProjectLinkORM."""
        # Construct project URL from project namespace and slug
        project_path = f"/p/{self.project.slug.namespace.slug}/{self.project.slug.slug}"

        return models.DataConnectorToProjectLink(
            id=self.id,
            data_connector_id=self.data_connector_id,
            project_id=self.project_id,
            project_path=project_path,
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
