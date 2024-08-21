"""SQLAlchemy schemas for the cloud storage database."""

from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, MetaData, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column, relationship
from sqlalchemy.schema import Index, UniqueConstraint
from ulid import ULID

from renku_data_services.secrets.orm import SecretORM
from renku_data_services.storage import models
from renku_data_services.users.orm import UserORM

JSONVariant = JSON().with_variant(JSONB(), "postgresql")

metadata_obj = MetaData(schema="storage")  # Has to match alembic ini section name


class BaseORM(MappedAsDataclass, DeclarativeBase):
    """Base class for all ORM classes."""

    metadata = metadata_obj


class CloudStorageORM(BaseORM):
    """A cloud storage that can be mounted to a project."""

    __tablename__ = "cloud_storage"

    project_id: Mapped[str] = mapped_column("project_id", String(), index=True)
    """Id of the project."""

    storage_type: Mapped[str] = mapped_column("storage_type", String(20))
    """Type of storage (e.g. s3), read-only based on 'configuration'."""

    configuration: Mapped[dict[str, Any]] = mapped_column("configuration", JSONVariant)
    """RClone configuration dict."""

    source_path: Mapped[str] = mapped_column("source_path", String())
    """Source path to mount from (e.g. bucket/folder for s3)."""

    target_path: Mapped[str] = mapped_column("target_path", String())
    """Target folder in the repository to mount to."""

    name: Mapped[str] = mapped_column("name", String())
    """Name of the cloud storage"""

    readonly: Mapped[bool] = mapped_column("readonly", Boolean(), default=True)
    """Whether this storage should be mounted readonly or not """

    storage_id: Mapped[str] = mapped_column(
        "storage_id", String(26), primary_key=True, default_factory=lambda: str(ULID()), init=False
    )
    """Id of this storage."""

    secrets: Mapped[list["CloudStorageSecretsORM"]] = relationship(
        lazy="noload", init=False, viewonly=True, default_factory=list
    )
    """Saved secrets for the storage."""

    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "name",
            name="_unique_name_uc",
        ),
    )

    @classmethod
    def load(cls, storage: models.CloudStorage) -> "CloudStorageORM":
        """Create CloudStorageORM from the cloud storage model."""
        return cls(
            project_id=storage.project_id,
            name=storage.name,
            storage_type=storage.storage_type,
            configuration=storage.configuration.model_dump(),
            source_path=storage.source_path,
            target_path=storage.target_path,
            readonly=storage.readonly,
        )

    def dump(self) -> models.CloudStorage:
        """Create a cloud storage model from the ORM object."""
        return models.CloudStorage(
            project_id=self.project_id,
            name=self.name,
            storage_type=self.storage_type,
            configuration=models.RCloneConfig(config=self.configuration),
            source_path=self.source_path,
            target_path=self.target_path,
            storage_id=self.storage_id,
            readonly=self.readonly,
            secrets=[s.dump() for s in self.secrets],
        )


class CloudStorageSecretsORM(BaseORM):
    """Secrets for cloud storages."""

    __tablename__ = "cloud_storage_secrets"
    __table_args__ = (Index("ix_storage_cloud_storage_secrets_user_id_storage_id", "user_id", "storage_id"),)

    user_id: Mapped[str] = mapped_column(
        "user_id", ForeignKey(UserORM.keycloak_id, ondelete="CASCADE"), primary_key=True
    )

    storage_id: Mapped[str] = mapped_column(
        "storage_id", ForeignKey(CloudStorageORM.storage_id, ondelete="CASCADE"), primary_key=True
    )

    name: Mapped[str] = mapped_column("name", String(), primary_key=True)

    secret_id: Mapped[str] = mapped_column("secret_id", ForeignKey(SecretORM.id, ondelete="CASCADE"))
    secret: Mapped[SecretORM] = relationship(init=False, repr=False, lazy="selectin")

    @classmethod
    def load(cls, storage_secret: models.CloudStorageSecret) -> "CloudStorageSecretsORM":
        """Create an instance from the cloud storage secret model."""
        return cls(
            user_id=storage_secret.user_id,
            storage_id=storage_secret.storage_id,
            name=storage_secret.name,
            secret_id=storage_secret.secret_id,
        )

    def dump(self) -> models.CloudStorageSecret:
        """Create a cloud storage secret model from the ORM object."""
        return models.CloudStorageSecret(
            user_id=self.user_id, storage_id=self.storage_id, name=self.name, secret_id=self.secret_id
        )
