"""Access token verification for the MCP server (HTTP mode).

The MCP specification requires a server to verify that an access token was issued for
it specifically, rather than accepting any token the caller happens to present. Without
this check a token minted for another Renku client — the UI, the CLI — is accepted here
and grants the full tool surface.

Keycloak ignores the RFC 8707 ``resource`` parameter, so the audience is instead added by
an audience mapper on the ``renku-mcp`` client. The resulting access token carries both
that audience and the one the Renku data API expects, which is why the token can still be
forwarded downstream unchanged.

The JWKS lookup and ``jwt.decode`` call here overlap with
``renku_data_services.authn.keycloak.KeycloakAuthenticator``. That class is not reused
because importing it pulls in sanic, sqlalchemy and the data API's app config — around 159
modules — into what is otherwise a standalone service with six dependencies. It also
hardcodes the data API's own audience list and returns an APIUser, neither of which fits
here. The shared part is small enough to live twice for now; extracting it into a leaf
module under ``authn`` that both call is the eventual fix.
"""

from __future__ import annotations

import logging
import os

import jwt
from jwt import PyJWKClient

logger = logging.getLogger(__name__)

DEFAULT_AUDIENCE = "renku-mcp"
_DISCOVERY_PATH = "/.well-known/openid-configuration"


class TokenVerifier:
    """Verifies access tokens against the Keycloak realm that issued them.

    The signing keys are fetched lazily on first use and cached by PyJWKClient, so a
    verifier can be constructed at startup without requiring Keycloak to be reachable
    yet.
    """

    def __init__(self, issuer_url: str, audience: str = DEFAULT_AUDIENCE, algorithms: list[str] | None = None) -> None:
        self.issuer_url = issuer_url.rstrip("/")
        self.audience = audience
        self.algorithms = algorithms or ["RS256"]
        self._jwks: PyJWKClient | None = None

    @classmethod
    def from_env(cls) -> TokenVerifier | None:
        """Build a verifier from the environment, or None when verification is disabled.

        Returns None only when KEYCLOAK_ISSUER_URL is unset, which the caller is expected
        to treat as a configuration error in HTTP mode.
        """
        issuer_url = os.environ.get("KEYCLOAK_ISSUER_URL", "").rstrip("/")
        if not issuer_url:
            return None
        return cls(issuer_url=issuer_url, audience=os.environ.get("RENKU_MCP_AUDIENCE", DEFAULT_AUDIENCE))

    @property
    def jwks(self) -> PyJWKClient:
        """The JWKS client for this realm, created on first use."""
        if self._jwks is None:
            self._jwks = PyJWKClient(f"{self.issuer_url}/protocol/openid-connect/certs")
        return self._jwks

    def verify(self, token: str) -> dict[str, object]:
        """Return the token's claims.

        Checks the signature, the issuer, the expiry and — the point of the exercise —
        that this server is among the token's audiences.

        Raises PyJWT's own exceptions, which already distinguish the cases a caller needs
        to tell apart: jwt.InvalidTokenError (and its subclasses) means the token is bad,
        while PyJWKClientError means the signing keys could not be fetched and nothing
        could be decided. Those warrant different answers to the client, so they are not
        flattened into one error type here.
        """
        signing_key = self.jwks.get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            key=signing_key.key,
            algorithms=self.algorithms,
            audience=self.audience,
            issuer=self.issuer_url,
            options={"require": ["exp", "aud", "iss"]},
        )
