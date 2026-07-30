"""SQLAlchemy schemas for the data project storage database."""

from __future__ import annotations

from datetime import datetime
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, MetaData, String, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column
from ulid import ULID

from renku_data_services.base_models.bytesize import ByteSize
from renku_data_services.base_orm.registry import COMMON_ORM_REGISTRY
from renku_data_services.project.orm import ProjectORM
from renku_data_services.storage import models
from renku_data_services.users.orm import UserORM
from renku_data_services.utils.sqlalchemy import ByteSizeType, PurePosixPathType, ULIDType

if TYPE_CHECKING:
    pass


class BaseORM(MappedAsDataclass, DeclarativeBase):
    """Base class for all ORM classes."""

    metadata = MetaData(schema="storage")
    registry = COMMON_ORM_REGISTRY


class ProjectStorageAllowORM(BaseORM):
    """ORM model for project storage allow list with size limits."""

    __tablename__ = "project_storage_allow"

    project_id: Mapped[ULID] = mapped_column(
        "project_id",
        ForeignKey(ProjectORM.id, ondelete="CASCADE"),
        primary_key=True,
        unique=True,
        index=True,
    )
    """ID of the project."""

    max_size: Mapped[ByteSize] = mapped_column("max_size", ByteSizeType())
    """Maximum allowed size in bytes."""

    updated_at: Mapped[datetime] = mapped_column(
        "updated_at",
        DateTime(timezone=True),
        default=None,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def dump(self) -> models.ProjectStorageAllow:
        """Convert the ORM row to a ProjectStorageAllow model."""
        return models.ProjectStorageAllow(
            project_id=self.project_id,
            max_size=self.max_size,
            updated_at=self.updated_at,
        )


class ProjectStorageORM(BaseORM):
    """ORM model for project storage configuration."""

    __tablename__ = "project_storage"

    id: Mapped[ULID] = mapped_column(
        "id", ULIDType, primary_key=True, server_default=text("generate_ulid()"), init=False
    )
    project_id: Mapped[ULID] = mapped_column(
        ForeignKey(ProjectStorageAllowORM.project_id, ondelete="CASCADE"), index=True, nullable=False, unique=True
    )
    """ID of the project (must exist in project_storage_allow)."""

    storage_class: Mapped[str] = mapped_column("storage_class", String(20))
    """The storage class (e.g. azurefile)."""

    size_limit: Mapped[ByteSize] = mapped_column("size_limit", ByteSizeType())
    """The storage limit in bytes."""

    mount_path: Mapped[PurePosixPath] = mapped_column("target_path", PurePosixPathType())
    """Folder to mount to."""

    created_by_id: Mapped[str] = mapped_column(ForeignKey(UserORM.keycloak_id), index=True, nullable=False)
    """User ID of the creator of the project storage."""

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

    def dump(self) -> models.ProjectStorage:
        """Convert the ORM row to a ProjectStorage model."""
        return models.ProjectStorage(
            id=self.id,
            project_id=self.project_id,
            storage_class=self.storage_class,
            size=self.size_limit,
            mount_path=self.mount_path,
            created_by=self.created_by_id,
            creation_date=self.creation_date,
            updated_at=self.updated_at,
        )
