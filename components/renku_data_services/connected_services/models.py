"""Models for connected services."""
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from renku_data_services.connected_services.apispec import ConnectionStatus


@dataclass(frozen=True, eq=True, kw_only=True)
class OAuth2Client(BaseModel):
    """OAuth2 Client model."""

    id: str
    client_id: str
    display_name: str
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
class OAuth2TokenSet(BaseModel):
    """OAuth2 token set model."""

    access_token: str
    refresh_token: str
    expires_at: int

    @classmethod
    def from_dict(cls, token_set: dict[str, Any]):
        """Create an OAuth2 token set a dictionary."""
        return cls(**token_set)

    def to_dict(self) -> dict:
        """Return this token set as a dictionary."""
        return dict(
            access_token=self.access_token,
    refresh_token=self.refresh_token,
    expires_at=self.expires_at
        )
