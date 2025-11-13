"""SQLAlchemy schemas for the notifications database."""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, MetaData, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column
from ulid import ULID

from renku_data_services.notifications import models
from renku_data_services.utils.sqlalchemy import ULIDType

metadata_obj = MetaData(schema="notifications")


class BaseORM(MappedAsDataclass, DeclarativeBase):
    """Base class for all ORM classes."""

    metadata = metadata_obj


class AlertORM(BaseORM):
    """The alerts."""

    __tablename__ = "alerts"

    id: Mapped[ULID] = mapped_column("id", ULIDType, primary_key=True, default=lambda: str(ULID()), init=False)
    """ID of the alert."""

    title: Mapped[str] = mapped_column("title", String(), nullable=False)
    """Title of the alert."""

    message: Mapped[str] = mapped_column("message", String(), nullable=False)
    """Message of the alert."""

    user_id: Mapped[str] = mapped_column("user_id", String(), nullable=False)
    """ID of the user the alert is for."""

    session_name: Mapped[Optional[str]] = mapped_column("session_name", String(), default=None)
    """Name of the session the alert is for, if any."""

    creation_date: Mapped[datetime] = mapped_column(
        "creation_date", DateTime(timezone=True), default=None, server_default=func.now(), nullable=False
    )
    """Creation date and time."""

    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        "resolved_at", DateTime(timezone=True), default=None, nullable=True
    )
    """Date and time when the alert was resolved, if applicable."""

    def dump(self) -> models.Alert:
        """Create an alert model from the AlertORM."""
        return models.Alert(
            id=self.id,
            title=self.title,
            message=self.message,
            user_id=self.user_id,
            session_name=self.session_name,
            creation_date=self.creation_date,
            resolved_at=self.resolved_at,
        )
