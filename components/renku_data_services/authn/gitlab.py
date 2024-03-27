"""Gitlab authenticator."""

import contextlib
import urllib.parse as parse
from dataclasses import dataclass

import gitlab
from sanic import Request

import renku_data_services.base_models as base_models
from renku_data_services import errors


@dataclass
class GitlabAuthenticator:
    """Authenticator for gitlab repos.

    Note:
        Once we have a project service, this should get information on what type of git provider is used from there
        and support different backends.
    """

    gitlab_url: str

    token_field: str = "Gitlab-Access-Token"

    def __post_init__(self):
        """Properly set gitlab url."""
        parsed_url = parse.urlparse(self.gitlab_url)

        if not parsed_url.scheme:
            self.gitlab_url = f"https://{self.gitlab_url}"

    async def authenticate(self, access_token: str, request: Request) -> base_models.APIUser:
        """Checks the validity of the access token."""
        if self.token_field != "Authorization":  # nosec: B105
            access_token = str(request.headers.get(self.token_field))

        result = await self._get_gitlab_api_user(access_token)
        return result

    async def _get_gitlab_api_user(self, access_token: str) -> base_models.APIUser:
        """Get and validate a Gitlab API User."""
        client = gitlab.Gitlab(self.gitlab_url, oauth_token=access_token)
        try:
            client.auth()  # needed for the user property to be set
        except gitlab.GitlabAuthenticationError:
            raise errors.Unauthorized(message="User not authorized with Gitlab")
        user = client.user
        if user is None:
            raise errors.Unauthorized(message="User not authorized with Gitlab")

        if user.state != "active":
            raise errors.Unauthorized(message="User isn't active in Gitlab")

        user_id = user.id

        if user_id is None:
            raise errors.Unauthorized(message="Could not get user id")

        full_name: str | None = user.name
        last_name: str | None = None
        first_name: str | None = None
        email: str | None = user.email
        if full_name:
            name_parts = full_name.split()
            with contextlib.suppress(IndexError):
                first_name = name_parts.pop(0)
            if len(name_parts) >= 1:
                last_name = " ".join(name_parts)

        return base_models.APIUser(
            is_admin=False,
            id=str(user_id),
            access_token=access_token,
            first_name=first_name,
            last_name=last_name,
            email=email,
            full_name=full_name,
        )
