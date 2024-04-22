"""SQLAlchemy schemas for the connected services database."""
from datetime import datetime

from sqlalchemy import DateTime, MetaData, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column

from renku_data_services.connected_services import models

metadata_obj = MetaData(schema="connected_services")

class BaseORM(MappedAsDataclass, DeclarativeBase):
    """Base class for all ORM classes."""

    metadata = metadata_obj

class OAuth2ClientORM(BaseORM):
    """An OAuth2 Client."""

    __tablename__ = "oauth2_clients"
    id: Mapped[str] = mapped_column("id", String(99), primary_key=True)
    client_id: Mapped[str] = mapped_column("client_id", String(500))
    display_name: Mapped[str] = mapped_column("display_name", String(99))
    created_by_id: Mapped[str] = mapped_column("created_by_id", String())
    creation_date: Mapped[datetime] = mapped_column(
        "creation_date", DateTime(timezone=True), default=None,  server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        "updated_at", DateTime(timezone=True), default=None, server_default=func.now(), onupdate=func.now(),
        nullable=False
    )

    def dump(self, redacted: bool = True) -> models.OAuth2Client:
        """Create an OAuth2 Client model from the OAuth2ClientORM."""
        return models.OAuth2Client(
            id=self.id,
            client_id=self.client_id if not redacted else "",
            display_name=self.display_name,
            created_by_id=self.created_by_id,
            creation_date=self.creation_date,
            updated_at=self.updated_at,
        )
