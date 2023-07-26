"""SQLAlchemy schemas for the cloud storage database."""
from typing import Any

import renku_data_services.storage_models as models
from sqlalchemy import JSON, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column
from ulid import ULID

JSONVariant = JSON().with_variant(JSONB(), "postgresql")


class BaseORM(MappedAsDataclass, DeclarativeBase):
    """Base class for all ORM classes."""

    pass


class CloudStorageORM(BaseORM):
    """A cloud storage that can be mounted to a project."""

    __tablename__ = "cloud_storage"

    git_url: Mapped[str] = mapped_column("git_url", String(), index=True)
    storage_type: Mapped[str] = mapped_column("storage_type", String(20))
    configuration: Mapped[dict[str, Any]] = mapped_column("configuration", JSONVariant)

    storage_id: Mapped[str] = mapped_column(
        "storage_id", String(26), primary_key=True, default_factory=lambda: str(ULID()), init=False
    )

    @classmethod
    def load(cls, storage: models.CloudStorage):
        """Create CloudStorageORM from the cloud storage model."""
        return cls(git_url=storage.git_url, storage_type=storage.storage_type, configuration=storage.configuration)

    def dump(self):
        """Create a cloud storage model from the ORM object."""
        return models.CloudStorage(
            git_url=self.git_url,
            storage_type=self.storage_type,
            configuration=self.configuration,
            storage_id=self.storage_id,
        )
