"""Keycloak user store."""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, cast

import httpx
import jwt
from jwt import PyJWKClient
from sanic import Request

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.utils.core import get_ssl_context


@dataclass
class KcUserStore:
    """Wrapper around checking if users exist in Keycloak."""

    keycloak_url: str
    realm: str = "Renku"

    def __post_init__(self):
        self.keycloak_url = self.keycloak_url.rstrip("/")

    async def get_user_by_id(self, id: str, access_token: str) -> Optional[base_models.User]:
        """Get a user by their unique id."""
        url = f"{self.keycloak_url}/admin/realms/{self.realm}/users/{id}"
        async with httpx.AsyncClient(verify=get_ssl_context()) as client:
            res = await client.get(url=url, headers={"Authorization": f"bearer {access_token}"})
        if res.status_code == 200 and cast(Dict, res.json()).get("id") == id:
            return base_models.User(keycloak_id=id)
        return None


@dataclass
class KeycloakAuthenticator:
    """Authenticator for JWT access tokens from Keycloak."""

    jwks: PyJWKClient
    algorithms: List[str]
    admin_role: str = "renku-admin"
    token_field: str = "Authorization"

    def __post_init__(self):
        if len(self.algorithms) == 0:
            raise errors.ConfigurationError(message="At least one algorithm for token validation has to be specified.")

    def _validate(self, token: str) -> Dict[str, Any]:
        sk = self.jwks.get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            key=sk.key,
            algorithms=self.algorithms,
            audience=["renku", "renku-ui", "renku-cli", "swagger"],
            verify=True,
        )

    async def authenticate(self, access_token: str, request: Request) -> base_models.APIUser:
        """Checks the validity of the access token."""
        if self.token_field != "Authorization":  # nosec: B105
            access_token = str(request.headers.get(self.token_field))

        parsed = self._validate(access_token)
        is_admin = self.admin_role in parsed.get("realm_access", {}).get("roles", [])
        return base_models.APIUser(
            is_admin=is_admin,
            id=parsed.get("sub"),
            access_token=access_token,
            name=parsed.get("name"),
            first_name=parsed.get("given_name"),
            last_name=parsed.get("family_name"),
            email=parsed.get("email"),
        )
