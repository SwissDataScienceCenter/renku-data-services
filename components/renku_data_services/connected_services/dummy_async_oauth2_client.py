"""Dummy adapter for OAuth2 operations."""

from urllib.parse import urlparse

from authlib.integrations.httpx_client import AsyncOAuth2Client
from authlib.oauth2.auth import OAuth2Token
from httpx._models import Response


class DummyAsyncOAuth2Client(AsyncOAuth2Client):
    """A dummy adapter for OAuth2 operations."""

    async def fetch_token(self, *args, **kwargs) -> OAuth2Token:
        """Stub getting a token set."""
        return OAuth2Token.from_dict(
            dict(access_token="ACCESS_TOKEN", refresh_token="REFRESH_TOKEN", expires_in=3600)  # nosec
        )

    async def get(self, url: str, *args, **kwargs) -> Response:
        """Stub a `GET` request."""
        parsed = urlparse(url)

        if parsed.path == "/api/v4/user":
            return self._get_account_response()

        return Response(500, json=dict())

    @staticmethod
    def _get_account_response() -> Response:
        user = dict(
            username="USERNAME",
            web_url="https://example.org/USERNAME",
        )
        return Response(200, json=user)
