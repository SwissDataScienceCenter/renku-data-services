"""SQLAlchemy schemas for the CRC database."""

from datetime import datetime
from typing import Optional

from renku_data_services.users import models
from sqlalchemy import DateTime, ForeignKey, LargeBinary, MetaData, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column

from renku_data_services.base_models import Slug
from renku_data_services.users.models import UserInfo
from ulid import ULID


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
    secret_key: Mapped[Optional[str]] = mapped_column(String(64), default=None)
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

    def to_slug(self) -> Slug:
        """Convert the User ORM object to a namespace slug."""
        if self.email:
            slug = self.email.split("@")[0]
        elif self.first_name and self.last_name:
            slug = self.first_name + "-" + self.last_name
        elif self.last_name:
            slug = self.last_name
        elif self.first_name:
            slug = self.first_name
        else:
            slug = "user_" + self.keycloak_id
        # The length limit is 99 but leave some space for modifications that may be added down the line
        # to filter out invalid characters or to generate a unique name
        slug = slug[:80]
        return Slug.from_name(slug)


class LastKeycloakEventTimestamp(BaseORM):
    """The latest event timestamp processed from Keycloak."""

    __tablename__ = "last_keycloak_event_timestamp"
    id: Mapped[int] = mapped_column(primary_key=True, init=False)
    timestamp_utc: Mapped[datetime] = mapped_column(DateTime(timezone=False), default_factory=datetime.utcnow)


class SecretORM(BaseORM):
    """Secret table."""

    __tablename__ = "secrets"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "name",
            name="_unique_name_user",
        ),
    )
    name: Mapped[str] = mapped_column(String(256))
    encrypted_value: Mapped[bytes] = mapped_column(LargeBinary())
    modification_date: Mapped[datetime] = mapped_column("modification_date", DateTime(timezone=True))
    id: Mapped[str] = mapped_column("id", String(26), primary_key=True, default_factory=lambda: str(ULID()), init=False)
    user_id: Mapped[Optional[str]] = mapped_column(
        "user_id", ForeignKey(UserORM.id, ondelete="CASCADE", nullable=True), default=None, index=True
    )

    def dump(self) -> models.Secret:
        """Create a secret object from the ORM object."""
        return models.Secret(
            id=self.id,
            name=self.name,
            encrypted_value=self.encrypted_value,
            modification_date=self.modification_date,
        )

    @classmethod
    def load(cls, secret: models.Secret):
        """Create an ORM object from the user object."""
        return cls(
            name=secret.name,
            encrypted_value=secret.encrypted_value,
            modification_date=secret.modification_date,
        )
