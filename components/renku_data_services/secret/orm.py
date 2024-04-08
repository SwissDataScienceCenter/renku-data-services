"""SQLAlchemy's schemas for the secrets database."""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, MetaData, String
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column
from ulid import ULID

from renku_data_services.secrets_storage.secret import models
from renku_data_services.utils.cryptography import decrypt_string, encrypt_string

metadata_obj = MetaData(schema="secrets")  # Has to match alembic ini section name


class BaseORM(MappedAsDataclass, DeclarativeBase):
    """Base class for all ORM classes."""

    metadata = metadata_obj


class SecretORM(BaseORM):
    """A secret."""

    __tablename__ = "secrets"

    id: Mapped[str] = mapped_column(
        "id",
        String(26),
        primary_key=True,
        default_factory=lambda: str(ULID()),
        init=False,
    )
    name: Mapped[str] = mapped_column("name", String(99))
    modification_date: Mapped[Optional[datetime]] = mapped_column(
        "modification_date", DateTime(timezone=True)
    )
    value: Mapped[str] = mapped_column("value", String(5000))
    user_id: Mapped[str] = mapped_column("user_id", String(36), index=True)

    @classmethod
    def load(cls, secret: models.Secret, user_id: str, password: bytes, salt: str):
        """Create an instance from the secret model."""
        return cls(
            name=secret.name,
            value=encrypt_string(password=password, salt=salt, data=secret.value),
            modification_date=secret.modification_date,
            user_id=user_id,
        )

    def dump(self, password: bytes, salt: str) -> models.Secret:
        """Create a secret model."""
        return models.Secret(
            id=self.id,
            name=self.name,
            value=decrypt_string(password=password, salt=salt, data=self.value),
            modification_date=self.modification_date,
        )
