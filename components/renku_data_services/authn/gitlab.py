"""Gitlab authenticator."""

import base64
import contextlib
import json
import re
import urllib.parse as parse
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from typing import Any

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
        try:
            client.auth()  # needed for the user property to be set
        except gitlab.GitlabAuthenticationError:
            raise errors.UnauthorizedError(message="User not authorized with Gitlab")
        user = client.user
        if user is None:
            raise errors.UnauthorizedError(message="User not authorized with Gitlab")

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

        _, _, _, expires_at = self.git_creds_from_headers(headers)
        return base_models.APIUser(
            id=str(user_id),
            access_token=access_token,
            first_name=first_name,
            last_name=last_name,
            email=email,
            full_name=full_name,
            access_token_expires_at=expires_at,
        )

    @staticmethod
    def git_creds_from_headers(headers: Header) -> tuple[Any, Any, Any, datetime | None]:
        """Extract git credentials from the encoded header sent by the gateway."""
        parsed_dict = json.loads(base64.decodebytes(headers["Renku-Auth-Git-Credentials"].encode()))
        git_url, git_credentials = next(iter(parsed_dict.items()))
        token_match = re.match(r"^[^\s]+\ ([^\s]+)$", git_credentials["AuthorizationHeader"])
        git_token = token_match.group(1) if token_match is not None else None
        git_token_expires_at_raw = git_credentials["AccessTokenExpiresAt"]
        git_token_expires_at_num: float | None = None
        with suppress(ValueError, TypeError):
            git_token_expires_at_num = float(git_token_expires_at_raw)
        git_token_expires_at: datetime | None = None
        if git_token_expires_at_num is not None and git_token_expires_at_num > 0:
            with suppress(ValueError):
                git_token_expires_at = datetime.fromtimestamp(git_token_expires_at_num)
        return (
            git_url,
            git_credentials["AuthorizationHeader"],
            git_token,
            git_token_expires_at,
        )
