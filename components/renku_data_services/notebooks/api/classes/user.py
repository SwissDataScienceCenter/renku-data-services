"""Notebooks user model definitions."""

import base64
import json
import re
from functools import lru_cache
from math import floor
from typing import Any, Optional, Protocol, cast

import escapism
import jwt
from gitlab import Gitlab
from gitlab.v4.objects.projects import Project
from gitlab.v4.objects.users import CurrentUser
from sanic.log import logger

from ...errors.user import AuthenticationError


class User(Protocol):
    """Representation of a user that is calling the API."""

    access_token: str | None = None
    git_token: str | None = None
    gitlab_client: Gitlab
    username: str

    @lru_cache(maxsize=8)
    def get_renku_project(self, namespace_project: str) -> Optional[Project]:
        """Retrieve the GitLab project."""
        try:
            return self.gitlab_client.projects.get(f"{namespace_project}")
        except Exception as e:
            logger.warning(f"Cannot get project: {namespace_project} for user: {self.username}, error: {e}")
        return None

    @property
    def anonymous(self) -> bool:
        """Indicates whether the user is anonymous or not."""
        return False


class AnonymousUser(User):
    """Anonymous user."""

    auth_header = "Renku-Auth-Anon-Id"

    def __init__(self, headers: dict, gitlab_url: str):
        self.authenticated = (
            self.auth_header in headers
            and headers[self.auth_header] != ""
            # The anonymous id must start with an alphanumeric character
            and re.match(r"^[a-zA-Z0-9]", headers[self.auth_header]) is not None
        )
        if not self.authenticated:
            return
        self.git_url = gitlab_url
        self.gitlab_client = Gitlab(self.git_url, api_version="4", per_page=50)
        self.username = headers[self.auth_header]
        self.safe_username = escapism.escape(self.username, escape_char="-").lower()
        self.full_name = None
        self.email = None
        self.oidc_issuer = None
        self.git_token = None
        self.git_token_expires_at = 0
        self.access_token = None
        self.refresh_token = None
        self.id = headers[self.auth_header]

    def __str__(self) -> str:
        return f"<Anonymous user id:{self.username[:5]}****>"

    @property
    def anonymous(self) -> bool:
        """Indicates whether the user is anonymous."""
        return True


class RegisteredUser(User):
    """Registered user."""

    auth_headers = [
        "Renku-Auth-Access-Token",
        "Renku-Auth-Id-Token",
    ]
    git_header = "Renku-Auth-Git-Credentials"

    def __init__(self, headers: dict[str, str]):
        self.authenticated = all([header in headers for header in self.auth_headers])
        if not self.authenticated:
            return
        if not headers.get(self.git_header):
            raise AuthenticationError(
                "Your Gitlab credentials are invalid or expired, "
                "please login Renku, or fully log out and log back in."
            )

        parsed_id_token = self.parse_jwt_from_headers(headers)
        self.email = parsed_id_token["email"]
        self.full_name = parsed_id_token["name"]
        self.username = parsed_id_token["preferred_username"]
        self.safe_username = escapism.escape(self.username, escape_char="-").lower()
        self.oidc_issuer = parsed_id_token["iss"]
        self.id = parsed_id_token["sub"]
        self.access_token = headers["Renku-Auth-Access-Token"]
        self.refresh_token = headers["Renku-Auth-Refresh-Token"]

        (
            self.git_url,
            self.git_auth_header,
            self.git_token,
            self.git_token_expires_at,
        ) = self.git_creds_from_headers(headers)
        self.gitlab_client = Gitlab(
            self.git_url,
            api_version="4",
            oauth_token=self.git_token,
            per_page=50,
        )

    @property
    def gitlab_user(self) -> CurrentUser | None:
        """Get the Gitlab user."""
        if not getattr(self.gitlab_client, "user", None):
            self.gitlab_client.auth()
        return self.gitlab_client.user

    @staticmethod
    def parse_jwt_from_headers(headers: dict[str, str]) -> dict[str, Any]:
        """Parse the JWT."""
        # No need to verify the signature because this is already done by the gateway
        decoded = jwt.decode(headers["Renku-Auth-Id-Token"], options={"verify_signature": False})
        decoded = cast(dict[str, Any], decoded)
        return decoded

    @staticmethod
    def git_creds_from_headers(headers: dict[str, str]) -> tuple[str, str, str, int]:
        """Extract the git credentials from a header."""
        parsed_dict = json.loads(base64.decodebytes(headers["Renku-Auth-Git-Credentials"].encode()))
        git_url, git_credentials = next(iter(parsed_dict.items()))
        if not isinstance(git_url, str) or not isinstance(git_credentials, dict):
            raise AuthenticationError(message="Could not successfully decode the git credentials header")
        token_match = re.match(r"^[^\s]+\ ([^\s]+)$", git_credentials["AuthorizationHeader"])
        git_token = token_match.group(1) if token_match is not None else None
        if not isinstance(git_token, str):
            raise AuthenticationError(message="Could not successfully decode the git credentials header")
        git_token_expires_at = git_credentials.get("AccessTokenExpiresAt")
        if git_token_expires_at is None:
            # INFO: Indicates that the token does not expire
            git_token_expires_at = -1
        else:
            try:
                # INFO: Sometimes this can be a float, sometimes an int
                git_token_expires_at = float(git_token_expires_at)
            except ValueError:
                git_token_expires_at = -1
            else:
                git_token_expires_at = floor(git_token_expires_at)
        return (
            git_url,
            git_credentials["AuthorizationHeader"],
            git_token,
            git_token_expires_at,
        )

    def __str__(self) -> str:
        return f"<Registered user username:{self.username} name: " f"{self.full_name} email: {self.email}>"
