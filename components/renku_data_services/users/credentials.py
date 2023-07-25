"""Wrapper around JWT signature validation with JWK."""
from dataclasses import dataclass
from typing import Any, Dict, List

import jwt
import renku_data_services.base_models as base_models
from jwt import PyJWKClient

from renku_data_services import errors


@dataclass
class KeycloakAuthenticator:
    """Authenticator for JWT access tokens from Keycloak."""

    jwks: PyJWKClient
    algorithms: List[str]
    admin_role: str = "renku-admin"

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

    async def authenticate(self, access_token: str) -> base_models.APIUser:
        """Checks the validity of the access token."""
        parsed = self._validate(access_token)
        is_admin = self.admin_role in parsed.get("realm_access", {}).get("roles", [])
        return base_models.APIUser(is_admin, parsed.get("sub"), access_token=access_token)
