"""SQLAlchemy schemas for the connected services database."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, LargeBinary, MetaData, String, false, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column, relationship
from sqlalchemy.schema import UniqueConstraint
from ulid import ULID

from renku_data_services.connected_services import models
from renku_data_services.utils.sqlalchemy import ULIDType

JSONVariant = JSON().with_variant(JSONB(), "postgresql")

metadata_obj = MetaData(schema="connected_services")


class BaseORM(MappedAsDataclass, DeclarativeBase):
    """Base class for all ORM classes."""

    metadata = metadata_obj


class OAuth2ClientORM(BaseORM):
    """An OAuth2 Client."""

    __tablename__ = "oauth2_clients"
    id: Mapped[str] = mapped_column("id", String(99), primary_key=True)
    client_id: Mapped[str] = mapped_column("client_id", String(500), repr=False)
    display_name: Mapped[str] = mapped_column("display_name", String(99))
    created_by_id: Mapped[str] = mapped_column("created_by_id", String())
    kind: Mapped[models.ProviderKind]
    scope: Mapped[str] = mapped_column("scope", String())
    url: Mapped[str] = mapped_column("url", String())
    use_pkce: Mapped[bool] = mapped_column("use_pkce", Boolean(), server_default=false())
    app_slug: Mapped[str] = mapped_column("app_slug", String(500), default="", server_default="")
    client_secret: Mapped[bytes | None] = mapped_column("client_secret", LargeBinary(), default=None, repr=False)
    creation_date: Mapped[datetime] = mapped_column(
        "creation_date", DateTime(timezone=True), default=None, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        "updated_at",
        DateTime(timezone=True),
        default=None,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    image_registry_url: Mapped[str | None] = mapped_column(default=None, nullable=True, server_default=None)
    oidc_issuer_url: Mapped[str | None] = mapped_column(default=None, nullable=True, server_default=None)

    def dump(self, user_is_admin: bool = False) -> models.OAuth2Client:
        """Create an OAuth2 Client model from the OAuth2ClientORM.

        Some fields will be redacted if the user is not an admin user.
        """
        return models.OAuth2Client(
            id=self.id,
            kind=self.kind,
            app_slug=self.app_slug,
            client_id=self.client_id if user_is_admin else "",
            client_secret="redacted" if self.client_secret and user_is_admin else "",
            display_name=self.display_name,
            scope=self.scope,
            url=self.url,
            use_pkce=self.use_pkce,
            created_by_id=self.created_by_id,
            creation_date=self.creation_date,
            updated_at=self.updated_at,
            image_registry_url=self.image_registry_url,
            oidc_issuer_url=self.oidc_issuer_url,
        )


class OAuth2ConnectionORM(BaseORM):
    """An OAuth2 connection."""

    __tablename__ = "oauth2_connections"
    id: Mapped[ULID] = mapped_column("id", ULIDType, primary_key=True, default_factory=lambda: str(ULID()), init=False)
    user_id: Mapped[str] = mapped_column("user_id", String())
    client_id: Mapped[str] = mapped_column(ForeignKey(OAuth2ClientORM.id, ondelete="CASCADE"), index=True)
    client: Mapped[OAuth2ClientORM] = relationship(init=False, repr=False)
    token: Mapped[dict[str, Any] | None] = mapped_column("token", JSONVariant)
    state: Mapped[str | None] = mapped_column("state", String(), index=True, unique=True)
    status: Mapped[models.ConnectionStatus]
    code_verifier: Mapped[str | None] = mapped_column("code_verifier", String())
    next_url: Mapped[str | None] = mapped_column("next_url", String())
    creation_date: Mapped[datetime] = mapped_column(
        "creation_date", DateTime(timezone=True), default=None, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        "updated_at",
        DateTime(timezone=True),
        default=None,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "client_id",
            name="_unique_user_id_client_id_uc",
        ),
    )

    def dump(self) -> models.OAuth2Connection:
        """Create an OAuth2 connection model from the OAuth2ConnectionORM."""
        return models.OAuth2Connection(
            id=self.id, provider_id=self.client_id, status=self.status, next_url=self.next_url
        )
