"""Dummy adapter for OAuth2 operations."""

from urllib.parse import urlparse

from authlib.integrations.httpx_client import AsyncOAuth2Client
from authlib.oauth2.auth import OAuth2Token
from httpx._models import Response


class DummyAsyncOAuth2Client(AsyncOAuth2Client):  # type: ignore[misc]
    """A dummy adapter for OAuth2 operations."""

    async def fetch_token(self, *args: list, **kwargs: dict) -> OAuth2Token:
        """Stub getting a token set."""
        return OAuth2Token.from_dict(
            dict(access_token="ACCESS_TOKEN", refresh_token="REFRESH_TOKEN", expires_in=3600)  # nosec
        )

    async def get(self, url: str, *args: list, **kwargs: dict) -> Response:
        """Stub a `GET` request."""
        parsed = urlparse(url)

        if parsed.path == "/api/v4/user":
            return self._get_account_response()

        if parsed.path == "/api/v4/projects/username%2Fmy_repo":
            return self._get_repository_response()

        if parsed.path == "/api/v3/user/installations" or parsed.path == "/user/installations":
            return self._get_installations_response()

        return Response(500, json={"error": f"path is not expected: {parsed.path}"})

    @staticmethod
    def _get_account_response() -> Response:
        user = dict(
            username="USERNAME",
            web_url="https://example.org/USERNAME",
        )
        return Response(200, json=user)

    @staticmethod
    def _get_repository_response() -> Response:
        repository = dict(
            http_url_to_repo="https://example.org/username/my_repo.git",
            web_url="https://example.org/username/my_repo",
            permissions=dict(
                project_access=dict(access_level=20),
                group_access=None,
            ),
            visibility="private",
        )
        return Response(200, json=repository)

    @staticmethod
    def _get_installations_response() -> Response:
        repository = dict(
            total_count=1,
            installations=[
                dict(
                    id=12345,
                    account=dict(
                        login="USERNAME",
                        html_url="https://example.org/USERNAME",
                    ),
                    repository_selection="all",
                    suspended_at=None,
                )
            ],
        )
        return Response(200, json=repository)
