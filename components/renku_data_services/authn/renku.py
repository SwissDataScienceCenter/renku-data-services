"""Renku data services self authenticator.

This authenticator can mint and verify its own tokens.
"""

from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final, Self

import jwt
from sanic import Request
from ulid import ULID

from renku_data_services.app_config.config import InternalAuthenticationConfig
from renku_data_services.base_models.core import AnonymousAPIUser, APIUser, AuthenticatedAPIUser, Authenticator
from renku_data_services.errors import errors

if TYPE_CHECKING:
    from renku_data_services.app_config.config import InternalAuthenticationConfig

_strict_jwt = jwt.PyJWT({"enforce_minimum_key_length": True})

# TODO: make these configurable (from usual config)
_EXPIRATION: Final[timedelta] = timedelta(minutes=5)
_ISSUER: Final[str] = "renku-self"
_AUDIENCE: Final[str] = "renku-self"


@dataclass(frozen=True, kw_only=True)
class RenkuSelfAuthenticator(Authenticator[APIUser]):
    """Renku data services self authenticator.

    This authenticator can mint and verify its own tokens.
    """

    secret_key: bytes = field(repr=False)
    algorithm: str = "HS512"
    token_field: str = "Authorization"
    anon_id_header_key: str = "Renku-Auth-Anon-Id"
    anon_id_cookie_name: str = "Renku-Auth-Anon-Id"

    @classmethod
    def from_config(cls, config: "InternalAuthenticationConfig") -> Self:
        """Create an instance from a configuration object."""
        return cls(secret_key=config.secret_key)

    async def authenticate(self, access_token: str, request: Request) -> APIUser:
        """Authenticate using internal tokens."""

        header_value = str(request.headers.get(self.token_field)) or ""
        user: AuthenticatedAPIUser | AnonymousAPIUser | None = None

        with suppress(errors.UnauthorizedError, jwt.InvalidTokenError):
            token = header_value.removeprefix("Bearer ").removeprefix("bearer ")
            parsed = self._validate(token)
            exp = parsed.get("exp")
            id = parsed.get("sub")
            email = parsed.get("email")
            if id is None or email is None:
                raise errors.UnauthorizedError(
                    message="Your credentials are invalid or expired, please log in again."
                ) from None

            user = AuthenticatedAPIUser(
                is_admin=False,
                id=id,
                access_token=token,
                full_name=parsed.get("name"),
                first_name=parsed.get("given_name"),
                last_name=parsed.get("family_name"),
                email=email,
                access_token_expires_at=datetime.fromtimestamp(exp) if exp is not None else None,
                roles=[],
            )
            request.ctx.renku_authenticator = f"{self.__class__.__module__}.{self.__class__.__qualname__}"
            request.ctx.renku_user = user
            request.ctx.renku_parsed_access_token = parsed
            return user

        # Try to get an anonymous user ID if the validation of keycloak credentials failed
        anon_id = request.headers.get(self.anon_id_header_key)
        if anon_id is None:
            anon_id = request.cookies.get(self.anon_id_cookie_name)
        if anon_id is None:
            anon_id = f"anon-{str(ULID())}"
        user = AnonymousAPIUser(id=str(anon_id))

        return user

    def _validate(self, token: str) -> dict[str, Any]:
        return _strict_jwt.decode(
            token,
            key=self.secret_key,
            algorithms=[self.algorithm],
            issuer=_ISSUER,
            audience=_AUDIENCE,
        )


@dataclass(frozen=True, kw_only=True)
class RenkuSelfTokenMint:
    """Renku data services token mint.

    Creates internal tokens for authentication. Internal tokens are used by sessions and their sidecar services.
    """

    secret_key: bytes = field(repr=False)
    algorithm: str = "HS512"

    @classmethod
    def from_config(cls, config: "InternalAuthenticationConfig") -> Self:
        """Create an instance from a configuration object."""
        return cls(secret_key=config.secret_key)

    def create_token(self, user: APIUser, scope: str | None = None) -> str:
        """Create a new internal token for a given user."""
        payload = self._make_payload(user=user, scope=scope)
        return _strict_jwt.encode(payload, key=self.secret_key, algorithm=self.algorithm)

    def get_expires_in(self) -> int:
        """Get the value in seconds for the 'expires_in' claim."""
        return int(_EXPIRATION.total_seconds())

    @staticmethod
    def _make_payload(user: APIUser, scope: str | None = None) -> dict[str, str | int]:
        """Generate the payload for a new token."""
        result: dict[str, str | int] = dict()
        user_claims = RenkuSelfTokenMint._make_user_claims(user=user)
        result.update(user_claims)
        token_id = ULID()
        now = datetime.now(UTC)
        result["exp"] = int((now + _EXPIRATION).timestamp())
        result["iat"] = int(now.timestamp())
        result["nbf"] = int(now.timestamp()) - 1
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
