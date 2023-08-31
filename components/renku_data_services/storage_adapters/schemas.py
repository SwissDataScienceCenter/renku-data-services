"""SQLAlchemy schemas for the cloud storage database."""
from typing import Any

from sqlalchemy import JSON, Boolean, MetaData, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column
from sqlalchemy.schema import UniqueConstraint
from ulid import ULID

import renku_data_services.storage_models as models

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

    private: Mapped[bool] = mapped_column("private", Boolean(), default=False)
    """Whether the storage is private (requires credentials) or not """

    storage_id: Mapped[str] = mapped_column(
        "storage_id", String(26), primary_key=True, default_factory=lambda: str(ULID()), init=False
    )
    """Id of this storage."""

    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "name",
            name="_unique_name_uc",
        ),
    )

    @classmethod
    def load(cls, storage: models.CloudStorage):
        """Create CloudStorageORM from the cloud storage model."""
        return cls(
            project_id=storage.project_id,
            name=storage.name,
            storage_type=storage.storage_type,
            configuration=storage.configuration.model_dump(),
            source_path=storage.source_path,
            target_path=storage.target_path,
            private=storage.private,
        )

    def dump(self):
        """Create a cloud storage model from the ORM object."""
        return models.CloudStorage(
            project_id=self.project_id,
            name=self.name,
            storage_type=self.storage_type,
            configuration=models.RCloneConfig(config=self.configuration),
            source_path=self.source_path,
            target_path=self.target_path,
            storage_id=self.storage_id,
            private=self.private,
        )
