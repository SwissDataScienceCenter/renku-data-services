"""Renku data services self authenticator.

This authenticator can mint and verify its own tokens.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Final

from sanic import Request
from ulid import ULID

from renku_data_services.base_models.core import APIUser, Authenticator
from renku_data_services.errors import errors

# _strict_jwt = jwt.PyJWT({"enforce_minimum_key_length": True})

# TODO: make these configurable (from usual config)
_EXPIRATION: Final[timedelta] = timedelta(minutes=5)
_ISSUER: Final[str] = "renku-self"
_AUDIENCE: Final[str] = "renku-self"


@dataclass(frozen=True, kw_only=True)
class RenkuSelfAuthenticator(Authenticator[APIUser]):
    """Renku data services self authenticator.

    This authenticator can mint and verify its own tokens.
    """

    secret_key: str = field(init=False, repr=False)
    algorithm: str = "HS512"
    token_field: str = "Authorization"

    async def authenticate(self, access_token: str, request: Request) -> APIUser:
        """Validate the bearer token."""

        # _strict_jwt.decode

        raise NotImplementedError()

    @staticmethod
    def _make_payload(user: APIUser, scope: str | None = None) -> dict[str, str | int]:
        """Generate the payload for a new token."""
        result: dict[str, str | int] = dict()
        user_claims = RenkuSelfAuthenticator._make_user_claims(user=user)
        result.update(user_claims)
        token_id = ULID()
        now = datetime.now(UTC)
        result["exp"] = int((now + _EXPIRATION).timestamp())
        result["iat"] = int(now.timestamp())
        result["nbf"] = result["iat"]
        result["iss"] = _ISSUER
        result["aud"] = _AUDIENCE
        result["jti"] = str(token_id)
        if scope:
            result["scope"] = scope
        return result

    @staticmethod
    def _make_user_claims(user: APIUser) -> dict[str, str]:
        """Generate user claims from a user instance."""
        if not user.is_authenticated or not user.id or not user.email:
            raise errors.ProgrammingError(message="Cannot make user claims if not authenticated.")
        result: dict[str, str] = dict()
        result["sub"] = user.id
        result["email"] = user.email
        if user.full_name:
            result["name"] = user.full_name
        if user.first_name:
            result["given_name"] = user.first_name
        if user.last_name:
            result["family_name"] = user.last_name
        return result
