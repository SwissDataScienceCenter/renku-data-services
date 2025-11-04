"""SQLAlchemy schemas for the alerts database."""

from datetime import datetime

from sqlalchemy import DateTime, MetaData, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column
from ulid import ULID

from renku_data_services.notifications import models
from renku_data_services.utils.sqlalchemy import ULIDType

metadata_obj = MetaData(schema="common")


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

    creation_date: Mapped[datetime] = mapped_column(
        "creation_date", DateTime(timezone=True), default=None, server_default=func.now(), nullable=False
    )
    """Creation date and time."""

    def dump(self) -> models.Alert:
        """Create an alert model from the AlertORM."""
        return models.Alert(
            id=self.id,
            title=self.title,
            message=self.message,
            user_id=self.user_id,
            creation_date=self.creation_date,
        )
