"""Models for connected services."""
from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel


@dataclass(frozen=True, eq=True, kw_only=True)
class OAuth2Client(BaseModel):
    """OAuth2 Client model."""

    id: str
    client_id: str
    display_name: str
    created_by_id: str
    creation_date: datetime
    updated_at: datetime
