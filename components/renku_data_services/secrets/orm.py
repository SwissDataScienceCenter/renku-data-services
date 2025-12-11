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
    from renku_data_services.data_connectors.orm import DataConnectorSecretORM
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
            "default_filename",
            name="_unique_user_id_default_filename",
        ),
    )

    id: Mapped[ULID] = mapped_column("id", ULIDType, primary_key=True, default_factory=lambda: str(ULID()), init=False)
    """ID of this user secret."""

    name: Mapped[str] = mapped_column(String(99))
    """Name of the user secret."""

    default_filename: Mapped[str] = mapped_column(String(256))
    """Filename to give to this secret when mounted in Renku 1.0 sessions."""

    encrypted_value: Mapped[bytes] = mapped_column(LargeBinary())
    encrypted_key: Mapped[bytes] = mapped_column(LargeBinary())
    kind: Mapped[models.SecretKind]
    expiration_timestamp: Mapped[Optional[datetime]] = mapped_column(
        "expiration_timestamp", DateTime(timezone=True), default=None, nullable=True, index=True
    )
    modification_date: Mapped[datetime] = mapped_column(
        "modification_date",
        DateTime(timezone=True),
        default_factory=lambda: datetime.now(UTC),
        nullable=False,
    )

    user_id: Mapped[Optional[str]] = mapped_column(
        "user_id", ForeignKey(UserORM.keycloak_id, ondelete="CASCADE"), default=None, index=True, nullable=True
    )

    session_secrets: Mapped[list["SessionSecretORM"]] = relationship(
        init=False, repr=False, back_populates="secret", lazy="selectin", default_factory=list
    )

    data_connector_secrets: Mapped[list["DataConnectorSecretORM"]] = relationship(
        init=False, repr=False, back_populates="secret", lazy="selectin", default_factory=list
    )

    def dump(self) -> models.Secret:
        """Create a secret object from the ORM object."""
        return models.Secret(
            id=self.id,
            name=self.name,
            encrypted_value=self.encrypted_value,
            encrypted_key=self.encrypted_key,
            kind=self.kind,
            expiration_timestamp=self.expiration_timestamp,
            modification_date=self.modification_date,
            default_filename=self.default_filename,
            session_secret_slot_ids=[item.secret_slot_id for item in self.session_secrets],
            data_connector_ids=[item.data_connector_id for item in self.data_connector_secrets],
        )

    def update(self, encrypted_value: bytes, encrypted_key: bytes, expiration_timestamp: datetime | None) -> None:
        """Update an existing secret."""
        self.encrypted_value = encrypted_value
        self.encrypted_key = encrypted_key
        self.expiration_timestamp = expiration_timestamp
        self.modification_date = datetime.now(UTC)
