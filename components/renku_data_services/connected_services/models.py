"""Models for connected services."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel

from renku_data_services.connected_services.apispec import ConnectionStatus, ProviderKind


@dataclass(frozen=True, eq=True, kw_only=True)
class OAuth2Client:
    """OAuth2 Client model."""

    id: str
    kind: ProviderKind
    client_id: str
    client_secret: str | None
    display_name: str
    scope: str
    url: str
    created_by_id: str
    creation_date: datetime
    updated_at: datetime


@dataclass(frozen=True, eq=True, kw_only=True)
class OAuth2Connection:
    """OAuth2 connection model."""

    id: str
    provider_id: str
    status: ConnectionStatus


@dataclass(frozen=True, eq=True, kw_only=True)
class ConnectedAccount(BaseModel):
    """OAuth2 connected account model."""

    username: str
    web_url: str


@dataclass(frozen=True, eq=True, kw_only=True)
class GitHubConnectedAccount(BaseModel):
    """OAuth2 connected account model for GitHub."""

    login: str
    html_url: str

    def to_connected_account(self) -> ConnectedAccount:
        """Returns the corresponding ConnectedAccount object."""
        return ConnectedAccount(username=self.login, web_url=self.html_url)


class OAuth2TokenSet(dict):
    """OAuth2 token set model."""

    @classmethod
    def from_dict(cls, token_set: dict[str, Any]):
        """Create an OAuth2 token set from a dictionary."""
        if isinstance(token_set, dict) and not isinstance(token_set, cls):
            return cls(token_set)
        return token_set

    def dump_for_api(self) -> dict[str, Any]:
        """Expose the access token and other token metadata for API consumption."""
        data = dict((k, v) for k, v in self.items() if k != "refresh_token")
        if self.expires_at_iso is not None:
            data["expires_at_iso"] = self.expires_at_iso
        return data

    @property
    def access_token(self) -> str | None:
        """Returns the access token."""
        return self.get("access_token")

    @property
    def refresh_token(self) -> str | None:
        """Returns the refresh token."""
        return self.get("refresh_token")

    @property
    def expires_at(self) -> int | None:
        """Returns the access token expiry date."""
        return self.get("expires_at")

    @property
    def expires_at_iso(self) -> str | None:
        """Returns the access token expiry date."""
        if self.expires_at is None:
            return None
        return datetime.fromtimestamp(self.expires_at, UTC).isoformat()


@dataclass(frozen=True, eq=True, kw_only=True)
class RepositoryPermissions:
    """Repository permissions for git operations."""

    pull: bool
    push: bool

    @classmethod
    def default(cls):
        """Default permissions."""
        return cls(pull=False, push=False)


@dataclass(frozen=True, eq=True, kw_only=True)
class Repository:
    """Repository metadata."""

    etag: str | None
    git_http_url: str
    web_url: str
    permissions: RepositoryPermissions


class GitLabRepositoryPermissionAccess(BaseModel):
    """Repository permission access level from a GitLab provider."""

    access_level: int


class GitLabRepositoryPermissions(BaseModel):
    """Repository permissions from a GitLab provider."""

    GUEST_ACCESS_LEVEL = 10
    DEVELOPER_ACCESS_LEVEL = 30
    PUBLIC_VISIBILITY = "public"
    INTERNAL_VISIBILITY = "internal"

    project_access: GitLabRepositoryPermissionAccess | None
    group_access: GitLabRepositoryPermissionAccess | None

    def to_permissions(self, visibility: str) -> RepositoryPermissions:
        """Returns the corresponding RepositoryPermissions object."""
        pull = False
        push = False
        if visibility in [self.PUBLIC_VISIBILITY, self.INTERNAL_VISIBILITY]:
            pull = True
        if self.project_access is not None and self.project_access.access_level >= self.GUEST_ACCESS_LEVEL:
            pull = True
        if self.project_access is not None and self.project_access.access_level >= self.DEVELOPER_ACCESS_LEVEL:
            push = True
        if self.group_access is not None and self.group_access.access_level >= self.GUEST_ACCESS_LEVEL:
            pull = True
        if self.group_access is not None and self.group_access.access_level >= self.DEVELOPER_ACCESS_LEVEL:
            push = True
        return RepositoryPermissions(pull=pull, push=push)


@dataclass(frozen=True, eq=True, kw_only=True)
class GitLabRepository(BaseModel):
    """Repository metadata from a GitLab provider."""

    http_url_to_repo: str
    web_url: str
    permissions: GitLabRepositoryPermissions | None
    visibility: str

    def to_repository(self, etag: str | None) -> Repository:
        """Returns the corresponding Repository object."""
        return Repository(
            etag=etag if etag else None,
            git_http_url=self.http_url_to_repo,
            web_url=self.web_url,
            permissions=(
                self.permissions.to_permissions(visibility=self.visibility)
                if self.permissions is not None
                else RepositoryPermissions.default()
            ),
        )


class GitHubRepositoryPermissions(BaseModel):
    """Repository permissions from a GitHub provider."""

    pull: bool
    push: bool

    def to_permissions(self) -> RepositoryPermissions:
        """Returns the corresponding RepositoryPermissions object."""
        return RepositoryPermissions(pull=self.pull, push=self.push)


@dataclass(frozen=True, eq=True, kw_only=True)
class GitHubRepository(BaseModel):
    """Repository metadata from a GitHub provider."""

    clone_url: str
    html_url: str
    permissions: GitHubRepositoryPermissions | None
    visibility: str

    def to_repository(self, etag: str | None) -> Repository:
        """Returns the corresponding Repository object."""

        return Repository(
            etag=etag if etag else None,
            git_http_url=self.clone_url,
            web_url=self.html_url,
            permissions=(
                self.permissions.to_permissions() if self.permissions is not None else RepositoryPermissions.default()
            ),
        )
