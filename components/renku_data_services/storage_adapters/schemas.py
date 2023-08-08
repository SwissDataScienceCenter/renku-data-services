"""SQLAlchemy schemas for the cloud storage database."""
from typing import Any

from sqlalchemy import JSON, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column
from ulid import ULID

import renku_data_services.storage_models as models

JSONVariant = JSON().with_variant(JSONB(), "postgresql")


class BaseORM(MappedAsDataclass, DeclarativeBase):
    """Base class for all ORM classes."""

    pass


class CloudStorageORM(BaseORM):
    """A cloud storage that can be mounted to a project."""

    __tablename__ = "cloud_storage"

    project_id: Mapped[str] = mapped_column("project_id", String(), index=True)
    storage_type: Mapped[str] = mapped_column("storage_type", String(20))
    configuration: Mapped[dict[str, Any]] = mapped_column("configuration", JSONVariant)
    source_path: Mapped[str] = mapped_column("source_path", String())
    target_path: Mapped[str] = mapped_column("target_path", String())

    storage_id: Mapped[str] = mapped_column(
        "storage_id", String(26), primary_key=True, default_factory=lambda: str(ULID()), init=False
    )

    @classmethod
    def load(cls, storage: models.CloudStorage):
        """Create CloudStorageORM from the cloud storage model."""
        return cls(
            project_id=storage.project_id,
            storage_type=storage.storage_type,
            configuration=storage.configuration,
            source_path=storage.source_path,
            target_path=storage.target_path,
        )

    def dump(self):
        """Create a cloud storage model from the ORM object."""
        return models.CloudStorage(
            project_id=self.project_id,
            storage_type=self.storage_type,
            configuration=self.configuration,
            source_path=self.source_path,
            target_path=self.target_path,
            storage_id=self.storage_id,
        )
