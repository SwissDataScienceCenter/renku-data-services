"""Secrets ORM."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, LargeBinary, MetaData, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column, relationship
from ulid import ULID

from renku_data_services.base_orm.registry import COMMON_ORM_REGISTRY
from renku_data_services.secrets import models
from renku_data_services.users.orm import UserORM
from renku_data_services.utils.sqlalchemy import ULIDType

if TYPE_CHECKING:
    from renku_data_services.project.orm import SessionSecretORM


class BaseORM(MappedAsDataclass, DeclarativeBase):
    """Base class for all ORM classes."""

    metadata = MetaData(schema="secrets")
    registry = COMMON_ORM_REGISTRY


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
    encrypted_key: Mapped[bytes] = mapped_column(LargeBinary())
    kind: Mapped[models.SecretKind]
    modification_date: Mapped[datetime] = mapped_column(
        "modification_date", DateTime(timezone=True), default_factory=lambda: datetime.now(UTC).replace(microsecond=0)
    )
    id: Mapped[ULID] = mapped_column("id", ULIDType, primary_key=True, default_factory=lambda: str(ULID()), init=False)
    user_id: Mapped[Optional[str]] = mapped_column(
        "user_id", ForeignKey(UserORM.keycloak_id, ondelete="CASCADE"), default=None, index=True, nullable=True
    )

    session_secrets: Mapped[list["SessionSecretORM"]] = relationship(
        init=False, repr=False, back_populates="secret", lazy="selectin", default_factory=list
    )

    def dump(self) -> models.Secret:
        """Create a secret object from the ORM object."""
        secret = models.Secret(
            id=self.id,
            name=self.name,
            encrypted_value=self.encrypted_value,
            encrypted_key=self.encrypted_key,
            kind=self.kind,
            session_secret_ids=[item.id for item in self.session_secrets],
        )
        secret.modification_date = self.modification_date
        return secret

    @classmethod
    def load(cls, secret: models.UnsavedSecret) -> "SecretORM":
        """Create an ORM object from the user object."""
        return cls(
            name=secret.name,
            encrypted_value=secret.encrypted_value,
            encrypted_key=secret.encrypted_key,
            modification_date=secret.modification_date,
            kind=secret.kind,
        )

    def update(self, encrypted_value: bytes, encrypted_key: bytes) -> None:
        """Update an existing secret."""
        self.encrypted_value = encrypted_value
        self.encrypted_key = encrypted_key
        self.modification_date = datetime.now(UTC).replace(microsecond=0)
