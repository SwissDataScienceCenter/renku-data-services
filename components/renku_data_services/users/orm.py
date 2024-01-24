"""SQLAlchemy schemas for the CRC database."""
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, MetaData, String
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column

from renku_data_services.users.models import UserInfo


class BaseORM(MappedAsDataclass, DeclarativeBase):
    """Base class for all ORM classes."""

    metadata = MetaData(schema="users")  # Has to match alembic ini section name


class UserORM(BaseORM):
    """User data table."""

    __tablename__ = "users"
    keycloak_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(256), default=None)
    last_name: Mapped[Optional[str]] = mapped_column(String(256), default=None)
    email: Mapped[Optional[str]] = mapped_column(String(320), default=None, index=True)
    id: Mapped[int] = mapped_column(primary_key=True, init=False)

    def dump(self) -> UserInfo:
        """Create a user object from the ORM object."""
        return UserInfo(
            id=self.keycloak_id,
            first_name=self.first_name,
            last_name=self.last_name,
            email=self.email,
        )

    @classmethod
    def load(cls, user: UserInfo):
        """Create an ORM object from the user object."""
        return cls(
            keycloak_id=user.id,
            first_name=user.first_name,
            last_name=user.last_name,
            email=user.email,
        )


class LastKeycloakEventTimestamp(BaseORM):
    """The latest event timestamp processed from Keycloak."""

    __tablename__ = "last_keycloak_event_timestamp"
    id: Mapped[int] = mapped_column(primary_key=True, init=False)
    timestamp_utc: Mapped[datetime] = mapped_column(DateTime(timezone=False), default_factory=datetime.utcnow)
