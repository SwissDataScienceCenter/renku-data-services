"""Models for external API called by connected services."""

from datetime import datetime

from pydantic import BaseModel

from renku_data_services.connected_services import models
from renku_data_services.connected_services.apispec import RepositorySelection


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


class GitHubAppInstallation(BaseModel):
    """GitHub app installation."""

    id: int
    account: GitHubConnectedAccount
    repository_selection: RepositorySelection
    suspended_at: datetime | None = None

    def to_app_installation(self) -> models.AppInstallation:
        """Returns the corresponding AppInstallation object."""
        return models.AppInstallation(
            id=self.id,
            account_login=self.account.login,
            account_web_url=self.account.html_url,
            repository_selection=self.repository_selection,
            suspended_at=self.suspended_at,
        )


class GitHubAppInstallationList(BaseModel):
    """GitHub app installation list."""

    total_count: int
    installations: list[GitHubAppInstallation]

    def to_app_installation_list(self) -> models.AppInstallationList:
        """Returns the corresponding AppInstallationList object."""
        installations = [ins.to_app_installation() for ins in self.installations]
        return models.AppInstallationList(
            total_count=self.total_count,
            installations=installations,
        )
