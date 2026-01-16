"""Extra definitions for the API spec."""

from __future__ import annotations

from enum import StrEnum

from pydantic import ConfigDict

from renku_data_services.connected_services.apispec_base import BaseAPISpec


class PostTokenGrantType(StrEnum):
    """Grant type for token refresh."""

    refresh_token = "refresh_token"  # nosec B105


class PostTokenRequest(BaseAPISpec):
    """Body for a refresh token request."""

    model_config = ConfigDict(
        extra="forbid",
    )
    client_id: str
    client_secret: str
    grant_type: PostTokenGrantType
    refresh_token: str
