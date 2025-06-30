"""Gitlab authenticator."""

import contextlib
import urllib.parse as parse
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime

import gitlab
from sanic import Request
from sanic.compat import Header

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
    expires_at_field: str = "Gitlab-Access-Token-Expires-At"

    def __post_init__(self) -> None:
        """Properly set gitlab url."""
        parsed_url = parse.urlparse(self.gitlab_url)

        if not parsed_url.scheme:
            self.gitlab_url = f"https://{self.gitlab_url}"

    async def authenticate(self, access_token: str, request: Request) -> base_models.APIUser:
        """Checks the validity of the access token."""
        if self.token_field != "Authorization":  # nosec: B105
            access_token = str(request.headers.get(self.token_field))

        result = await self._get_gitlab_api_user(access_token, request.headers)
        return result

    async def _get_gitlab_api_user(self, access_token: str, headers: Header) -> base_models.APIUser:
        """Get and validate a Gitlab API User."""
        client = gitlab.Gitlab(self.gitlab_url, oauth_token=access_token)
        with suppress(gitlab.GitlabAuthenticationError):
            client.auth()  # needed for the user property to be set
        if client.user is None:
            # The user is not authenticated with Gitlab so we send out an empty APIUser
            # Anonymous Renku users will not be able to authenticate with Gitlab
            return base_models.APIUser()

        user = client.user

        if user.state != "active":
            raise errors.ForbiddenError(message="User isn't active in Gitlab")

        user_id = user.id

        if user_id is None:
            raise errors.UnauthorizedError(message="Could not get user id")

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

        expires_at: datetime | None = None
        expires_at_raw: str | None = headers.get(self.expires_at_field)
        if expires_at_raw is not None and len(expires_at_raw) > 0:
            with suppress(ValueError):
                expires_at = datetime.fromtimestamp(float(expires_at_raw))

        return base_models.APIUser(
            id=str(user_id),
            access_token=access_token,
            first_name=first_name,
            last_name=last_name,
            email=email,
            full_name=full_name,
            access_token_expires_at=expires_at,
        )


@dataclass
class EmptyGitlabAuthenticator:
    """An empty gitlab authenticator used to decouple gitlab from Renku."""

    token_field: str = "Not-Applicable"

    async def authenticate(self, _: str, __: Request) -> base_models.APIUser:
        """Always return an anonymous user."""
        return base_models.APIUser()
