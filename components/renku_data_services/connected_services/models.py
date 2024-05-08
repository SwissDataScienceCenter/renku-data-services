"""Models for connected services."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel

from renku_data_services.connected_services.apispec import ConnectionStatus, ProviderKind


@dataclass(frozen=True, eq=True, kw_only=True)
class OAuth2Client(BaseModel):
    """OAuth2 Client model."""

    id: str
    kind: ProviderKind
    client_id: str
    display_name: str
    scope: str
    url: str
    created_by_id: str
    creation_date: datetime
    updated_at: datetime


@dataclass(frozen=True, eq=True, kw_only=True)
class OAuth2Connection(BaseModel):
    """OAuth2 connection model."""

    id: str
    provider_id: str
    status: ConnectionStatus


@dataclass(frozen=True, eq=True, kw_only=True)
class ConnectedAccount(BaseModel):
    """OAuth2 connected account model."""

    username: str
    web_url: str

@dataclass(frozen=True, eq=True, kw_only=True)
class GitHubConnectedAccount(BaseModel):
    """OAuth2 connected account model for GitHub."""

    login: str
    html_url: str

    def to_connected_account(self) -> ConnectedAccount:
        """Returns the corresponding ConnectedAccount object."""
        return ConnectedAccount(username=self.login, web_url=self.html_url)


class OAuth2TokenSet(dict):
    """OAuth2 token set model."""

    @classmethod
    def from_dict(cls, token_set: dict[str, Any]):
        """Create an OAuth2 token set from a dictionary."""
        if isinstance(token_set, dict) and not isinstance(token_set, cls):
            return cls(token_set)
        return token_set

    def dump_for_api(self) -> dict[str, Any]:
        """Expose data for API consumption."""
        data = dict((k, v) for k, v in self.items() if k != "refresh_token")
        if self.expires_at_iso is not None:
            data['expires_at_iso'] = self.expires_at_iso
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
