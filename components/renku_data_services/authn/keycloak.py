"""Keycloak user store."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional, cast

import httpx
import jwt
from jwt import PyJWKClient
from sanic import Request
from tenacity import retry, stop_after_attempt, stop_after_delay, wait_fixed
from ulid import ULID

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.app_config.config import KeycloakConfig
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
        async with httpx.AsyncClient(verify=get_ssl_context(), timeout=5) as client:
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
    anon_id_header_key: str = "Renku-Auth-Anon-Id"
    anon_id_cookie_name: str = "Renku-Auth-Anon-Id"

    def __post_init__(self) -> None:
        if len(self.algorithms) == 0:
            raise errors.ConfigurationError(message="At least one algorithm for token validation has to be specified.")

    @classmethod
    def new(cls, kc_config: KeycloakConfig) -> KeycloakAuthenticator:
        """Create a new KeycloakAuthenticator instance."""

        @retry(stop=(stop_after_attempt(20) | stop_after_delay(300)), wait=wait_fixed(2), reraise=True)
        def oidc_discovery(kc_config: KeycloakConfig) -> dict[str, Any]:
            """Get OIDC configuration."""
            url = f"{kc_config.url}/realms/{kc_config.realm}/.well-known/openid-configuration"
            res = httpx.get(url, verify=get_ssl_context(), timeout=5)
            if res.status_code == 200:
                return cast(dict[str, Any], res.json())
            raise errors.ConfigurationError(message=f"Cannot successfully do OIDC discovery with url {url}.")

        oidc_disc_data = oidc_discovery(kc_config)
        jwks_url = oidc_disc_data.get("jwks_uri")
        if jwks_url is None:
            raise errors.ConfigurationError(
                message="The JWKS url for Keycloak cannot be found from the OIDC discovery endpoint."
            )
        jwks = PyJWKClient(jwks_url)
        if kc_config.algorithms is None:
            raise errors.ConfigurationError(message="At least one token signature algorithm is required.")

        return cls(jwks=jwks, algorithms=kc_config.algorithms)

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
        except jwt.InvalidTokenError as err:
            raise errors.InvalidTokenError(
                message="Your credentials are invalid or expired, please log in again."
            ) from err

    async def authenticate(
        self, access_token: str, request: Request
    ) -> base_models.AuthenticatedAPIUser | base_models.AnonymousAPIUser:
        """Checks the validity of the access token."""
        header_value = str(request.headers.get(self.token_field))
        refresh_token = request.headers.get(self.refresh_token_header)
        user: base_models.AuthenticatedAPIUser | base_models.AnonymousAPIUser | None = None

        # Try to get the authorization header for a fully authenticated user
        with suppress(errors.UnauthorizedError, jwt.InvalidTokenError):
            token = str(header_value).removeprefix("Bearer ").removeprefix("bearer ")
            parsed = self._validate(token)
            roles = parsed.get("realm_access", {}).get("roles", [])
            is_admin = self.admin_role in roles
            exp = parsed.get("exp")
            id = parsed.get("sub")
            email = parsed.get("email")

            if email is None:
                client_id = parsed.get("azp") or parsed.get("clientId") or parsed.get("client_id")
                if client_id:
                    email = f"service-account-{client_id}@renku.local"
                else:
                    raise errors.UnauthorizedError(
                        message="Your credentials are invalid or expired, please log in again."
                    ) from None

            if id is None:
                raise errors.UnauthorizedError(
                    message="Your credentials are invalid or expired, please log in again."
                ) from None

            user = base_models.AuthenticatedAPIUser(
                is_admin=is_admin,
                id=id,
                access_token=token,
                full_name=parsed.get("name"),
                first_name=parsed.get("given_name"),
                last_name=parsed.get("family_name"),
                email=email,
                refresh_token=str(refresh_token) if refresh_token else None,
                access_token_expires_at=datetime.fromtimestamp(exp) if exp is not None else None,
                roles=roles,
            )
        if user is not None:
            return user

        # Try to get an anonymous user ID if the validation of keycloak credentials failed
        anon_id = request.headers.get(self.anon_id_header_key)
        if anon_id is None:
            anon_id = request.cookies.get(self.anon_id_cookie_name)
        if anon_id is None:
            anon_id = f"anon-{str(ULID())}"
        user = base_models.AnonymousAPIUser(id=str(anon_id))

        return user
