"""Secrets ORM."""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, LargeBinary, MetaData, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column
from ulid import ULID

from renku_data_services.secrets import models


class BaseORM(MappedAsDataclass, DeclarativeBase):
    """Base class for all ORM classes."""

    metadata = MetaData(schema="secrets")  # Has to match alembic ini section name


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
        "user_id", ForeignKey("users.users", ondelete="CASCADE"), default=None, index=True, nullable=True
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
