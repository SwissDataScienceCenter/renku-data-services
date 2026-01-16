"""Extra definitions for the API spec."""

from __future__ import annotations

import base64
from enum import StrEnum
from typing import Self

from pydantic import ConfigDict

from renku_data_services.connected_services.apispec_base import BaseAPISpec


class PostTokenGrantType(StrEnum):
    """Grant type for token refresh."""

    refresh_token = "refresh_token"  # nosec B105


class PostTokenRequest(BaseAPISpec):
    """Body for a refresh token request."""

    model_config = ConfigDict(
        extra="allow",
    )
    grant_type: PostTokenGrantType
    refresh_token: str


class RenkuTokens(BaseAPISpec):
    """Represents a set of authentication tokens used in Renku."""

    model_config = ConfigDict(
        extra="forbid",
    )
    access_token: str
    refresh_token: str

    def encode(self) -> str:
        """Encode the Renku tokens as a single URL-safe string."""
        as_json = self.model_dump_json()
        return base64.urlsafe_b64encode(as_json.encode("utf-8")).decode("utf-8")

    @classmethod
    def decode(cls, encoded: str) -> Self:
        """Decode a single string into a set of Renku tokens."""
        json_raw = base64.urlsafe_b64decode(encoded.encode("utf-8"))
        return cls.model_validate_json(json_raw)
