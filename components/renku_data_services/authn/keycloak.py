"""Keycloak user store."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional, cast

import httpx
import jwt
from jwt import PyJWKClient
from sanic import Request

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.base_models.core import Authenticator
from renku_data_services.utils.core import get_ssl_context


@dataclass
class KcUserStore:
    """Wrapper around checking if users exist in Keycloak."""

    keycloak_url: str
    realm: str = "Renku"

    def __post_init__(self) -> None:
        self.keycloak_url = self.keycloak_url.rstrip("/")

    async def get_user_by_id(self, id: str, access_token: str) -> Optional[base_models.User]:
        """Get a user by their unique id."""
        url = f"{self.keycloak_url}/admin/realms/{self.realm}/users/{id}"
        async with httpx.AsyncClient(verify=get_ssl_context()) as client:
            res = await client.get(url=url, headers={"Authorization": f"bearer {access_token}"})
        if res.status_code == 200 and cast(dict, res.json()).get("id") == id:
            return base_models.User(keycloak_id=id)
        return None


@dataclass
class KeycloakAuthenticator(Authenticator):
    """Authenticator for JWT access tokens from Keycloak."""

    jwks: PyJWKClient
    algorithms: list[str]
    admin_role: str = "renku-admin"
    token_field: str = "Authorization"
    refresh_token_header: str = "Renku-Auth-Refresh-Token"

    def __post_init__(self) -> None:
        if len(self.algorithms) == 0:
            raise errors.ConfigurationError(message="At least one algorithm for token validation has to be specified.")

    def _validate(self, token: str) -> dict[str, Any]:
        try:
            sk = self.jwks.get_signing_key_from_jwt(token)
            return cast(
                dict[str, Any],
                jwt.decode(
                    token,
                    key=sk.key,
                    algorithms=self.algorithms,
                    audience=["renku", "renku-ui", "renku-cli", "swagger"],
                    verify=True,
                ),
            )
        except (jwt.InvalidSignatureError, jwt.MissingRequiredClaimError):
            # NOTE: the above errors are subclasses of `InvalidToken` below but they will result from keycloak
            # misconfiguration most often rather than from the user having done something so we surface them.
            raise
        except jwt.InvalidTokenError:
            raise errors.UnauthorizedError(
                message="Your credentials are invalid or expired, please log in again.", quiet=True
            )

    async def authenticate(self, access_token: str, request: Request) -> base_models.APIUser:
        """Checks the validity of the access token."""
        if self.token_field != "Authorization":  # nosec: B105
            access_token = str(request.headers.get(self.token_field))

        parsed = self._validate(access_token)
        is_admin = self.admin_role in parsed.get("realm_access", {}).get("roles", [])
        exp = parsed.get("exp")
        return base_models.APIUser(
            is_admin_init=is_admin,
            id=parsed.get("sub"),
            access_token=access_token,
            full_name=parsed.get("name"),
            first_name=parsed.get("given_name"),
            last_name=parsed.get("family_name"),
            email=parsed.get("email"),
            refresh_token=request.headers.get(self.refresh_token_header),
            access_token_expires_at=datetime.fromtimestamp(exp) if exp is not None else None,
        )
