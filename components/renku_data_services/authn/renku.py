"""Renku data services self authentication.

Instances of `RenkuSelfTokenMint` can create internal access and refresh tokens
and instances of `RenkuSelfAuthenticator` can validate those tokens.
"""

from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal, Self

import jwt
from sanic import Request
from ulid import ULID

from renku_data_services.app_config.config import InternalAuthenticationConfig
from renku_data_services.base_models.core import AnonymousAPIUser, APIUser, AuthenticatedAPIUser, Authenticator
from renku_data_services.errors import errors

if TYPE_CHECKING:
    from renku_data_services.app_config.config import InternalAuthenticationConfig

TokenType = Literal["Bearer", "Refresh"]

_strict_jwt = jwt.PyJWT({"enforce_minimum_key_length": True})
"""Makes sure we use an appropriate secret key."""


@dataclass(frozen=True, kw_only=True)
class RenkuSelfAuthenticator(Authenticator[APIUser]):
    """Renku data services self authenticator.

    This authenticator authenticates requests based on internal access tokens.
    """

    secret_key: bytes = field(repr=False)
    issuer: str
    audience: str
    algorithm: str = "HS512"
    token_field: str = "Authorization"
    anon_id_header_key: str = "Renku-Auth-Anon-Id"
    anon_id_cookie_name: str = "Renku-Auth-Anon-Id"

    @classmethod
    def from_config(cls, config: "InternalAuthenticationConfig") -> Self:
        """Create an instance from a configuration object."""
        return cls(
            secret_key=config.secret_key,
            issuer=config.issuer,
            audience=config.audience,
        )

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

            token_type = parsed.get("typ")
            if str(token_type).lower() != "bearer":
                raise errors.UnauthorizedError() from None

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
            issuer=self.issuer,
            audience=self.audience,
        )

    async def verify_refresh_token(self, refresh_token: str) -> dict[str, Any] | None:
        """Verify the given refresh token.

        Returns parsed token claims if successful and None if the token is invalid.
        """
        with suppress(errors.UnauthorizedError, jwt.InvalidTokenError):
            parsed = self._validate(refresh_token)
            id = parsed.get("sub")
            email = parsed.get("email")
            if id is None or email is None:
                raise errors.UnauthorizedError(
                    message="Your credentials are invalid or expired, please log in again."
                ) from None
            token_type = parsed.get("typ")
            if str(token_type).lower() != "refresh":
                raise errors.UnauthorizedError() from None
            return parsed

        return None


@dataclass(frozen=True, kw_only=True)
class RenkuSelfTokenMint:
    """Renku data services token mint.

    Creates internal tokens for authentication. Internal tokens are used by sessions and their sidecar services.
    """

    secret_key: bytes = field(repr=False)
    default_access_token_expiration: timedelta
    default_refresh_token_expiration: timedelta
    long_refresh_token_expiration: timedelta
    issuer: str
    audience: str
    algorithm: str = "HS512"

    @classmethod
    def from_config(cls, config: "InternalAuthenticationConfig") -> Self:
        """Create an instance from a configuration object."""
        return cls(
            secret_key=config.secret_key,
            default_access_token_expiration=config.default_access_token_expiration,
            default_refresh_token_expiration=config.default_refresh_token_expiration,
            long_refresh_token_expiration=config.long_refresh_token_expiration,
            issuer=config.issuer,
            audience=config.audience,
        )

    def create_access_token(self, user: APIUser, scope: str | None = None, expires_in: timedelta | None = None) -> str:
        """Create a new internal access token for a given user."""
        payload = self._make_payload(user=user, token_type="Bearer", scope=scope, expires_in=expires_in)  # nosec B106
        return _strict_jwt.encode(payload, key=self.secret_key, algorithm=self.algorithm)

    def create_refresh_token(
        self, user: APIUser, scope: str | None = None, refresh_expires_in: timedelta | None = None
    ) -> str:
        """Create a new internal refresh token for a given user."""
        payload = self._make_payload(user=user, token_type="Refresh", scope=scope, expires_in=refresh_expires_in)  # nosec B106
        return _strict_jwt.encode(payload, key=self.secret_key, algorithm=self.algorithm)

    def _make_payload(
        self,
        user: APIUser,
        token_type: TokenType | None = None,
        scope: str | None = None,
        expires_in: timedelta | None = None,
    ) -> dict[str, str | int]:
        """Generate the payload for a new token."""
        token_type = token_type if token_type else "Bearer"  # nosec B106
        if expires_in is None and token_type == "Refresh":  # nosec B105
            expires_in = self.default_refresh_token_expiration
        elif expires_in is None:
            expires_in = self.default_access_token_expiration
        result: dict[str, str | int] = dict()
        user_claims = RenkuSelfTokenMint._make_user_claims(user=user)
        result.update(user_claims)
        token_id = ULID()
        now = datetime.now(UTC)
        result["exp"] = int((now + expires_in).timestamp())
        result["iat"] = int(now.timestamp())
        result["nbf"] = int(now.timestamp()) - 1
        result["iss"] = self.issuer
        result["aud"] = self.audience
        result["jti"] = str(token_id)
        result["typ"] = token_type
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
