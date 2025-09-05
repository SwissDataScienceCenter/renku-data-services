"""SQLAlchemy schemas for the platform configuration database."""

from datetime import datetime

from sqlalchemy import DateTime, MetaData, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column
from ulid import ULID

from renku_data_services.platform import models
from renku_data_services.utils.sqlalchemy import ULIDType

metadata_obj = MetaData(schema="platform")


class BaseORM(MappedAsDataclass, DeclarativeBase):
    """Base class for all ORM classes."""

    metadata = metadata_obj


class PlatformConfigORM(BaseORM):
    """The platform configuration."""

    __tablename__ = "config"

    id: Mapped[models.ConfigID] = mapped_column("id", primary_key=True)
    """ID of the configuration instance, can only be "config" (singleton)."""

    incident_banner: Mapped[str] = mapped_column("incident_banner", String(), default="")
    """The contents of the maintenance banner."""

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
            incident_banner=self.incident_banner,
            creation_date=self.creation_date,
            updated_at=self.updated_at,
        )


class UrlRedirectsORM(BaseORM):
    """The url redirects."""

    __tablename__ = "url_redirects"

    id: Mapped[ULID] = mapped_column("id", ULIDType, primary_key=True, default_factory=lambda: str(ULID()), init=False)

    source_url: Mapped[str] = mapped_column("source_url", String(), default="", unique=True, index=True)
    """The source URL for the redirect."""

    target_url: Mapped[str] = mapped_column("target_url", String(), default="", index=True)
    """The target URL for the redirect."""

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

    def dump(self) -> models.UrlRedirectConfig:
        """Create a UrlRedirectConfig from the UrlRedirectsORM."""
        return models.UrlRedirectConfig(
            id=self.id,
            source_url=self.source_url,
            target_url=self.target_url,
            creation_date=self.creation_date,
            updated_at=self.updated_at,
        )
