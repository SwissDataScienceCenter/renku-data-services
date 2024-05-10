import base64
import json
import re
from abc import ABC
from functools import lru_cache
from math import floor
from typing import Optional

import escapism
import jwt
from flask import current_app
from gitlab import Gitlab
from gitlab.v4.objects.projects import Project

from ...config import config
from ...errors.programming import ConfigurationError
from ...errors.user import AuthenticationError


class User(ABC):
    access_token = None
    git_token = None

    @lru_cache(maxsize=8)
    def get_renku_project(self, namespace_project) -> Optional[Project]:
        """Retrieve the GitLab project."""
        try:
            return self.gitlab_client.projects.get(f"{namespace_project}")
        except Exception as e:
            current_app.logger.warning(f"Cannot get project: {namespace_project} for user: {self.username}, error: {e}")

    @property
    def anonymous(self) -> bool:
        return False


class AnonymousUser(User):
    auth_header = "Renku-Auth-Anon-Id"

    def __init__(self, headers):
        if not config.anonymous_sessions_enabled:
            raise ConfigurationError(message="Anonymous sessions are not enabled.")
        self.authenticated = (
            self.auth_header in headers
            and headers[self.auth_header] != ""
            # The anonymous id must start with an alphanumeric character
            and re.match(r"^[a-zA-Z0-9]", headers[self.auth_header]) is not None
        )
        if not self.authenticated:
            return
        self.git_url = config.git.url
        self.gitlab_client = Gitlab(self.git_url, api_version=4, per_page=50)
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

    def __str__(self):
        return f"<Anonymous user id:{self.username[:5]}****>"

    @property
    def anonymous(self) -> bool:
        return True


class RegisteredUser(User):
    auth_headers = [
        "Renku-Auth-Access-Token",
        "Renku-Auth-Id-Token",
    ]
    git_header = "Renku-Auth-Git-Credentials"

    def __init__(self, headers):
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
            api_version=4,
            oauth_token=self.git_token,
            per_page=50,
        )

    @property
    def gitlab_user(self):
        if not getattr(self.gitlab_client, "user", None):
            self.gitlab_client.auth()
        return self.gitlab_client.user

    @staticmethod
    def parse_jwt_from_headers(headers):
        # No need to verify the signature because this is already done by the gateway
        return jwt.decode(headers["Renku-Auth-Id-Token"], options={"verify_signature": False})

    @staticmethod
    def git_creds_from_headers(headers):
        parsed_dict = json.loads(base64.decodebytes(headers["Renku-Auth-Git-Credentials"].encode()))
        git_url, git_credentials = next(iter(parsed_dict.items()))
        token_match = re.match(r"^[^\s]+\ ([^\s]+)$", git_credentials["AuthorizationHeader"])
        git_token = token_match.group(1) if token_match is not None else None
        git_token_expires_at = git_credentials["AccessTokenExpiresAt"]
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

    def __str__(self):
        return f"<Registered user username:{self.username} name: " f"{self.full_name} email: {self.email}>"
