"""Models for connected services."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from renku_data_services.connected_services.apispec import ConnectionStatus, ProviderKind


@dataclass(frozen=True, eq=True, kw_only=True)
class OAuth2Client:
    """OAuth2 Client model."""

    id: str
    kind: ProviderKind
    client_id: str
    client_secret: str | None
    display_name: str
    scope: str
    url: str
    use_pkce: bool
    created_by_id: str
    creation_date: datetime
    updated_at: datetime


@dataclass(frozen=True, eq=True, kw_only=True)
class OAuth2Connection:
    """OAuth2 connection model."""

    id: str
    provider_id: str
    status: ConnectionStatus


@dataclass(frozen=True, eq=True, kw_only=True)
class ConnectedAccount:
    """OAuth2 connected account model."""

    username: str
    web_url: str


class OAuth2TokenSet(dict):
    """OAuth2 token set model."""

    @classmethod
    def from_dict(cls, token_set: dict[str, Any]) -> "OAuth2TokenSet":
        """Create an OAuth2 token set from a dictionary."""
        if isinstance(token_set, dict) and not isinstance(token_set, cls):
            return cls(token_set)
        return token_set

    def dump_for_api(self) -> dict[str, Any]:
        """Expose the access token and other token metadata for API consumption."""
        data = dict((k, v) for k, v in self.items() if k != "refresh_token")
        if self.expires_at_iso is not None:
            data["expires_at_iso"] = self.expires_at_iso
        return data

    @property
    def access_token(self) -> str | None:
        """Returns the access token."""
        return self.get("access_token")

    @property
    def refresh_token(self) -> str | None:
        """Returns the refresh token."""
        return self.get("refresh_token")

    @property
    def expires_at(self) -> int | None:
        """Returns the access token expiry date."""
        return self.get("expires_at")

    @property
    def expires_at_iso(self) -> str | None:
        """Returns the access token expiry date."""
        if self.expires_at is None:
            return None
        return datetime.fromtimestamp(self.expires_at, UTC).isoformat()


@dataclass(frozen=True, eq=True, kw_only=True)
class RepositoryPermissions:
    """Repository permissions for git operations."""

    pull: bool
    push: bool

    @classmethod
    def default(cls) -> "RepositoryPermissions":
        """Default permissions."""
        return cls(pull=False, push=False)


@dataclass(frozen=True, eq=True, kw_only=True)
class RepositoryMetadata:
    """Repository metadata."""

    etag: str | None
    git_http_url: str
    web_url: str
    permissions: RepositoryPermissions


@dataclass(frozen=True, eq=True, kw_only=True)
class RepositoryProviderMatch:
    """Repository provider match data."""

    provider_id: str
    connection_id: str | None
    repository_metadata: RepositoryMetadata | None
