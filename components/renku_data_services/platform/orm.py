"""SQLAlchemy schemas for the platform configuration database."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, MetaData, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column

from renku_data_services.platform import models

metadata_obj = MetaData(schema="platform")


class BaseORM(MappedAsDataclass, DeclarativeBase):
    """Base class for all ORM classes."""

    metadata = metadata_obj


class PlatformConfigORM(BaseORM):
    """The platform configuration."""

    __tablename__ = "config"

    id: Mapped[models.ConfigID] = mapped_column("id", primary_key=True)
    """ID of the configuration instance, can only be "config" (singleton)."""

    disable_ui: Mapped[bool] = mapped_column("disable_ui", Boolean(), default=False)
    """Indicates wether to disable the User Interface of RenkuLab."""

    maintenance_banner: Mapped[str] = mapped_column("maintenance_banner", String(), default="")
    """The contents of the maintenance banner."""

    status_page_id: Mapped[str] = mapped_column("status_page_id", String(500), default="")
    """The ID of a site on statuspage.io."""

    creation_date: Mapped[datetime] = mapped_column(
        "creation_date", DateTime(timezone=True), default=None, server_default=func.now(), nullable=False
    )
    """Creation date and time."""

    updated_at: Mapped[datetime] = mapped_column(
        "updated_at",
        DateTime(timezone=True),
        default=None,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    """Date and time of the last update."""

    def dump(self) -> models.PlatformConfig:
        """Create a platform configuration model from the PlatformConfigORM."""
        return models.PlatformConfig(
            id=self.id,
            disable_ui=self.disable_ui,
            maintenance_banner=self.maintenance_banner,
            status_page_id=self.status_page_id,
            creation_date=self.creation_date,
            updated_at=self.updated_at,
        )
