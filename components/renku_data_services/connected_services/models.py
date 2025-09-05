"""Models for connected services."""

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from ulid import ULID


class ProviderKind(StrEnum):
    """The kind of platform we connnect to."""

    gitlab = "gitlab"
    github = "github"
    drive = "drive"
    onedrive = "onedrive"
    dropbox = "dropbox"
    generic_oidc = "generic_oidc"


class ConnectionStatus(StrEnum):
    """The status of a connection."""

    connected = "connected"
    pending = "pending"


class RepositorySelection(StrEnum):
    """The repository selection for GitHub applications."""

    all = "all"
    selected = "selected"


@dataclass(frozen=True, eq=True, kw_only=True)
class UnsavedOAuth2Client:
    """OAuth2 Client model."""

    id: str
    app_slug: str
    kind: ProviderKind
    client_id: str
    client_secret: str | None
    display_name: str
    scope: str
    url: str
    use_pkce: bool
    image_registry_url: str | None = None


@dataclass(frozen=True, eq=True, kw_only=True)
class OAuth2Client(UnsavedOAuth2Client):
    """OAuth2 Client model."""

    created_by_id: str
    creation_date: datetime
    updated_at: datetime


@dataclass(frozen=True, eq=True, kw_only=True)
class OAuth2ClientPatch:
    """Model for changes requested on a OAuth2 Client."""

    kind: ProviderKind | None
    app_slug: str | None
    client_id: str | None
    client_secret: str | None
    display_name: str | None
    scope: str | None
    url: str | None
    use_pkce: bool | None
    image_registry_url: str | None


@dataclass(frozen=True, eq=True, kw_only=True)
class OAuth2Connection:
    """OAuth2 connection model."""

    id: ULID
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
class AppInstallation:
    """A GitHub app installation."""

    id: int
    account_login: str
    account_web_url: str
    repository_selection: RepositorySelection
    suspended_at: datetime | None = None


@dataclass(frozen=True, eq=True, kw_only=True)
class AppInstallationList:
    """GitHub app installation list."""

    total_count: int
    installations: list[AppInstallation]
