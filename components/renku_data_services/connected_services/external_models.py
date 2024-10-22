"""Models for external API called by connected services."""

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


class GoogleDriveConnectedAccount(BaseModel):
    """OAuth2 connected account model for google drive."""

    name: str
    email: str

    def to_connected_account(self) -> models.ConnectedAccount:
        """Returns the corresponding ConnectedAccount object."""
        return models.ConnectedAccount(username=self.name, web_url=f"mailto:{self.email}")


class OneDriveConnectedAccount(BaseModel):
    """OAuth2 connected account model for onedrive."""

    givenname: str
    familyname: str
    email: str

    def to_connected_account(self) -> models.ConnectedAccount:
        """Returns the corresponding ConnectedAccount object."""
        return models.ConnectedAccount(
            username=" ".join(filter(None, [self.givenname, self.familyname])), web_url=f"mailto:{self.email}"
        )


class DropboxConnectedAccount(BaseModel):
    """OAuth2 connected account model for dropbox."""

    family_name: str | None
    given_name: str | None
    email: str

    def to_connected_account(self) -> models.ConnectedAccount:
        """Returns the corresponding ConnectedAccount object."""
        return models.ConnectedAccount(
            username=" ".join(filter(None, [self.given_name, self.family_name])), web_url=f"mailto:{self.email}"
        )
