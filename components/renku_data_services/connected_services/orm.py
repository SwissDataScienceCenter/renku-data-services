"""SQLAlchemy schemas for the connected services database."""

from datetime import datetime
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

from sqlalchemy import JSON, DateTime, ForeignKey, MetaData, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column, relationship
from sqlalchemy.schema import UniqueConstraint
from ulid import ULID

from renku_data_services import errors
from renku_data_services.connected_services import models
from renku_data_services.connected_services.apispec import ConnectionStatus, ProviderKind

JSONVariant = JSON().with_variant(JSONB(), "postgresql")

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
    kind: Mapped[ProviderKind]
    scope: Mapped[str] = mapped_column("scope", String())
    url: Mapped[str] = mapped_column("url", String())
    client_secret: Mapped[str | None] = mapped_column("client_secret", String(500), default=None)
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

    def dump(self, redacted: bool = True) -> models.OAuth2Client:
        """Create an OAuth2 Client model from the OAuth2ClientORM."""
        return models.OAuth2Client(
            id=self.id,
            kind=self.kind,
            client_id=self.client_id if not redacted else "",
            display_name=self.display_name,
            scope=self.scope,
            url=self.url,
            created_by_id=self.created_by_id,
            creation_date=self.creation_date,
            updated_at=self.updated_at,
        )

    @property
    def authorization_url(self) -> str:
        """The authorization URL for the OAuth2 protocol."""
        if not self.url:
            raise errors.ValidationError(message=f"URL not defined for provider {self.id}.")
        if self.kind == ProviderKind.github:
            return urljoin(self.url, "login/oauth/authorize")
        return urljoin(self.url, "oauth/authorize")

    @property
    def token_endpoint_url(self) -> str:
        """The token endpoint URL for the OAuth2 protocol."""
        if not self.url:
            raise errors.ValidationError(message=f"URL not defined for provider {self.id}.")
        if self.kind == ProviderKind.github:
            return urljoin(self.url, "login/oauth/access_token")
        return urljoin(self.url, "oauth/token")

    @property
    def api_url(self) -> str:
        """The URL used for API calls on the Resource Server."""
        if not self.url:
            raise errors.ValidationError(message=f"URL not defined for provider {self.id}.")
        if self.kind == ProviderKind.github:
            url = urlparse(self.url)
            url = url._replace(netloc=f"api.{url.netloc}")
            return urlunparse(url)
        return urljoin(self.url, "api/v4/")


class OAuth2ConnectionORM(BaseORM):
    """An OAuth2 connection."""

    __tablename__ = "oauth2_connections"
    id: Mapped[str] = mapped_column("id", String(26), primary_key=True, default_factory=lambda: str(ULID()), init=False)
    user_id: Mapped[str] = mapped_column("user_id", String())
    client_id: Mapped[str] = mapped_column(ForeignKey(OAuth2ClientORM.id, ondelete="CASCADE"), index=True)
    client: Mapped[OAuth2ClientORM] = relationship(init=False, repr=False)
    token: Mapped[dict[str, Any] | None] = mapped_column("token", JSONVariant)
    cookie: Mapped[str | None] = mapped_column("cookie", String(), index=True, unique=True)
    state: Mapped[str | None] = mapped_column("state", String())
    status: Mapped[ConnectionStatus]
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
        return models.OAuth2Connection(id=self.id, provider_id=self.client_id, status=self.status)
