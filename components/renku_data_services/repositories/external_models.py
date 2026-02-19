"""Models for external API called by connected services."""

from enum import Enum

from pydantic import BaseModel

from renku_data_services.repositories import models


class GitLabVisibility(Enum):
    """Visibilities in GitLab."""

    public = "public"
    internal = "internal"
    private = "private"


class GitLabPredifinedAccessLevels(Enum):
    """Predifined access levels in GitLab."""

    guest = 10
    developer = 30


class GitLabRepositoryPermissionAccess(BaseModel):
    """Repository permission access level from a GitLab provider."""

    access_level: int


class GitLabRepositoryPermissions(BaseModel):
    """Repository permissions from a GitLab provider."""

    project_access: GitLabRepositoryPermissionAccess | None
    group_access: GitLabRepositoryPermissionAccess | None

    def to_permissions(self, visibility: str | None) -> models.RepositoryPermissions:
        """Returns the corresponding models.RepositoryPermissions object."""
        pull = False
        push = False
        if visibility in [GitLabVisibility.public.value, GitLabVisibility.internal.value]:
            pull = True
        if (
            self.project_access is not None
            and self.project_access.access_level >= GitLabPredifinedAccessLevels.guest.value
        ):
            pull = True
        if (
            self.project_access is not None
            and self.project_access.access_level >= GitLabPredifinedAccessLevels.developer.value
        ):
            push = True
        if self.group_access is not None and self.group_access.access_level >= GitLabPredifinedAccessLevels.guest.value:
            pull = True
        if (
            self.group_access is not None
            and self.group_access.access_level >= GitLabPredifinedAccessLevels.developer.value
        ):
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
            visibility=(
                models.RepositoryVisibility.public
                if self.visibility == GitLabVisibility.public.value
                else models.RepositoryVisibility.private
            ),
        )


class GitHubVisibility(Enum):
    """Visibilities in GitHub."""

    public = "public"
    private = "private"


class GitHubRepositoryPermissions(BaseModel):
    """Repository permissions from a GitHub provider."""

    pull: bool
    push: bool

    def to_permissions(self, visibility: str | None) -> models.RepositoryPermissions:
        """Returns the corresponding models.RepositoryPermissions object."""
        pull = self.pull
        if visibility == GitHubVisibility.public.value:
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
            visibility=(
                models.RepositoryVisibility.public
                if self.visibility == GitHubVisibility.public.value
                else models.RepositoryVisibility.private
            ),
        )
