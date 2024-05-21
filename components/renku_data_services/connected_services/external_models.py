"""Models for external API called by connected services."""

from typing import ClassVar

from pydantic import BaseModel

from renku_data_services.connected_services import models


class GitLabConnectedAccount(BaseModel):
    """OAuth2 connected account model for GitLab."""

    username: str
    web_url: str

    def to_connected_account(self) -> models.ConnectedAccount:
        """Returns the corresponding ConnectedAccount object."""
        return models.ConnectedAccount(username=self.username, web_url=self.web_url)


class GitHubConnectedAccount(BaseModel):
    """OAuth2 connected account model for GitHub."""

    login: str
    html_url: str

    def to_connected_account(self) -> models.ConnectedAccount:
        """Returns the corresponding ConnectedAccount object."""
        return models.ConnectedAccount(username=self.login, web_url=self.html_url)


class GitLabRepositoryPermissionAccess(BaseModel):
    """Repository permission access level from a GitLab provider."""

    access_level: int


class GitLabRepositoryPermissions(BaseModel):
    """Repository permissions from a GitLab provider."""

    GUEST_ACCESS_LEVEL: ClassVar[int] = 10
    DEVELOPER_ACCESS_LEVEL: ClassVar[int] = 30
    PUBLIC_VISIBILITY: ClassVar[str] = "public"
    INTERNAL_VISIBILITY: ClassVar[str] = "internal"

    project_access: GitLabRepositoryPermissionAccess | None
    group_access: GitLabRepositoryPermissionAccess | None

    def to_permissions(self, visibility: str | None) -> models.RepositoryPermissions:
        """Returns the corresponding models.RepositoryPermissions object."""
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
        return models.RepositoryPermissions(pull=pull, push=push)


class GitLabRepository(BaseModel):
    """Repository metadata from a GitLab provider."""

    http_url_to_repo: str
    web_url: str
    permissions: GitLabRepositoryPermissions | None = None
    visibility: str | None = None

    def to_repository(
        self, etag: str | None, default_permissions: models.RepositoryPermissions | None = None
    ) -> models.RepositoryMetadata:
        """Returns the corresponding Repository object."""
        return models.RepositoryMetadata(
            etag=etag or None,
            git_http_url=self.http_url_to_repo,
            web_url=self.web_url,
            permissions=(
                self.permissions.to_permissions(visibility=self.visibility)
                if self.permissions is not None
                else default_permissions or models.RepositoryPermissions.default()
            ),
        )


class GitHubRepositoryPermissions(BaseModel):
    """Repository permissions from a GitHub provider."""

    PUBLIC_VISIBILITY: ClassVar[str] = "public"

    pull: bool
    push: bool

    def to_permissions(self, visibility: str | None) -> models.RepositoryPermissions:
        """Returns the corresponding models.RepositoryPermissions object."""
        pull = self.pull
        if visibility == self.PUBLIC_VISIBILITY:
            pull = True
        return models.RepositoryPermissions(pull=pull, push=self.push)


class GitHubRepository(BaseModel):
    """Repository metadata from a GitHub provider."""

    clone_url: str
    html_url: str
    permissions: GitHubRepositoryPermissions | None = None
    visibility: str

    def to_repository(
        self, etag: str | None, default_permissions: models.RepositoryPermissions | None = None
    ) -> models.RepositoryMetadata:
        """Returns the corresponding Repository object."""

        return models.RepositoryMetadata(
            etag=etag if etag else None,
            git_http_url=self.clone_url,
            web_url=self.html_url,
            permissions=(
                self.permissions.to_permissions(visibility=self.visibility)
                if self.permissions is not None
                else default_permissions or models.RepositoryPermissions.default()
            ),
        )
