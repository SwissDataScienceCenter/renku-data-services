"""Adapters for each kind of OAuth2 client."""

from abc import ABC, abstractmethod
from urllib.parse import urljoin, urlparse, urlunparse

from httpx import Response

from renku_data_services import errors
from renku_data_services.connected_services import external_models, models
from renku_data_services.connected_services import orm as schemas
from renku_data_services.connected_services.apispec import ProviderKind


class ProviderAdapter(ABC):
    """Defines the functionality of OAuth2 client adapters."""

    user_info_endpoint = "user"
    user_info_method = "GET"

    def __init__(self, client_url: str) -> None:
        self.client_url = client_url

    @property
    def authorization_url_extra_params(self) -> dict[str, str]:
        """Extra parameters to add to the auth url."""
        return {}

    @property
    @abstractmethod
    def authorization_url(self) -> str:
        """The authorization URL for the OAuth2 protocol."""
        ...

    @property
    @abstractmethod
    def token_endpoint_url(self) -> str:
        """The token endpoint URL for the OAuth2 protocol."""
        ...

    @property
    @abstractmethod
    def api_url(self) -> str:
        """The URL used for API calls on the Resource Server."""
        ...

    @property
    def api_common_headers(self) -> dict[str, str] | None:
        """The HTTP headers used for API calls on the Resource Server."""
        return None

    @abstractmethod
    def api_validate_account_response(self, response: Response) -> models.ConnectedAccount:
        """Validates and returns the connected account response from the Resource Server."""
        ...


class GitLabAdapter(ProviderAdapter):
    """Adapter for GitLab OAuth2 clients."""

    @property
    def authorization_url(self) -> str:
        """The authorization URL for the OAuth2 protocol."""
        return urljoin(self.client_url, "oauth/authorize")

    @property
    def token_endpoint_url(self) -> str:
        """The token endpoint URL for the OAuth2 protocol."""
        return urljoin(self.client_url, "oauth/token")

    @property
    def api_url(self) -> str:
        """The URL used for API calls on the Resource Server."""
        return urljoin(self.client_url, "api/v4/")

    def api_validate_account_response(self, response: Response) -> models.ConnectedAccount:
        """Validates and returns the connected account response from the Resource Server."""
        return external_models.GitLabConnectedAccount.model_validate(response.json()).to_connected_account()


class GitHubAdapter(ProviderAdapter):
    """Adapter for GitLab OAuth2 clients."""

    @property
    def authorization_url(self) -> str:
        """The authorization URL for the OAuth2 protocol."""
        return urljoin(self.client_url, "login/oauth/authorize")

    @property
    def token_endpoint_url(self) -> str:
        """The token endpoint URL for the OAuth2 protocol."""
        return urljoin(self.client_url, "login/oauth/access_token")

    @property
    def api_url(self) -> str:
        """The URL used for API calls on the Resource Server."""
        url = urlparse(self.client_url)
        url = url._replace(netloc=f"api.{url.netloc}")
        return urlunparse(url)

    @property
    def api_common_headers(self) -> dict[str, str] | None:
        """The HTTP headers used for API calls on the Resource Server."""
        return {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def api_validate_account_response(self, response: Response) -> models.ConnectedAccount:
        """Validates and returns the connected account response from the Resource Server."""
        return external_models.GitHubConnectedAccount.model_validate(response.json()).to_connected_account()

    def api_validate_app_installations_response(self, response: Response) -> models.AppInstallationList:
        """Validates and returns the app installations response from the Resource Server."""
        return external_models.GitHubAppInstallationList.model_validate(response.json()).to_app_installation_list()


class GoogleDriveAdapter(ProviderAdapter):
    """Adapter for Google Drive OAuth2 clients."""

    user_info_endpoint = "userinfo"

    @property
    def authorization_url(self) -> str:
        """The authorization URL for the OAuth2 protocol."""
        return "https://accounts.google.com/o/oauth2/auth"

    @property
    def authorization_url_extra_params(self) -> dict[str, str]:
        """Extra parameters to add to the auth url."""
        return {"access_type": "offline"}

    @property
    def token_endpoint_url(self) -> str:
        """The token endpoint URL for the OAuth2 protocol."""
        return "https://oauth2.googleapis.com/token"

    @property
    def api_url(self) -> str:
        """The URL used for API calls on the Resource Server."""
        return "https://www.googleapis.com/oauth2/v2/"

    @property
    def api_common_headers(self) -> dict[str, str] | None:
        """The HTTP headers used for API calls on the Resource Server."""
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def api_validate_account_response(self, response: Response) -> models.ConnectedAccount:
        """Validates and returns the connected account response from the Resource Server."""
        return external_models.GoogleDriveConnectedAccount.model_validate(response.json()).to_connected_account()


class OneDriveAdapter(ProviderAdapter):
    """Adapter for One Drive OAuth2 clients."""

    user_info_endpoint = "userinfo"

    @property
    def authorization_url(self) -> str:
        """The authorization URL for the OAuth2 protocol."""
        return "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"

    @property
    def authorization_url_extra_params(self) -> dict[str, str]:
        """Extra parameters to add to the auth url."""
        return {"access_type": "offline"}

    @property
    def token_endpoint_url(self) -> str:
        """The token endpoint URL for the OAuth2 protocol."""
        return "https://login.microsoftonline.com/common/oauth2/v2.0/token"

    @property
    def api_url(self) -> str:
        """The URL used for API calls on the Resource Server."""
        return "https://graph.microsoft.com/oidc/"

    @property
    def api_common_headers(self) -> dict[str, str] | None:
        """The HTTP headers used for API calls on the Resource Server."""
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def api_validate_account_response(self, response: Response) -> models.ConnectedAccount:
        """Validates and returns the connected account response from the Resource Server."""
        return external_models.OneDriveConnectedAccount.model_validate(response.json()).to_connected_account()


class DropboxAdapter(ProviderAdapter):
    """Adapter for Dropbox OAuth2 clients."""

    user_info_endpoint = "userinfo"
    user_info_method = "POST"

    @property
    def authorization_url(self) -> str:
        """The authorization URL for the OAuth2 protocol."""
        return "https://www.dropbox.com/oauth2/authorize"

    @property
    def authorization_url_extra_params(self) -> dict[str, str]:
        """Extra parameters to add to the auth url."""
        return {"access_type": "offline"}

    @property
    def token_endpoint_url(self) -> str:
        """The token endpoint URL for the OAuth2 protocol."""
        return "https://api.dropboxapi.com/oauth2/token"

    @property
    def api_url(self) -> str:
        """The URL used for API calls on the Resource Server."""
        return "https://api.dropboxapi.com/2/openid/"

    @property
    def api_common_headers(self) -> dict[str, str] | None:
        """The HTTP headers used for API calls on the Resource Server."""
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def api_validate_account_response(self, response: Response) -> models.ConnectedAccount:
        """Validates and returns the connected account response from the Resource Server."""
        return external_models.DropboxConnectedAccount.model_validate(response.json()).to_connected_account()


_adapter_map: dict[ProviderKind, type[ProviderAdapter]] = {
    ProviderKind.gitlab: GitLabAdapter,
    ProviderKind.github: GitHubAdapter,
    ProviderKind.drive: GoogleDriveAdapter,
    ProviderKind.onedrive: OneDriveAdapter,
    ProviderKind.dropbox: DropboxAdapter,
}


def get_provider_adapter(client: schemas.OAuth2ClientORM) -> ProviderAdapter:
    """Returns a new ProviderAdapter instance corresponding to the given client."""
    global _adapter_map

    if not client.url:
        raise errors.ValidationError(message=f"URL not defined for provider {client.id}.")

    adapter_class = _adapter_map[client.kind]
    return adapter_class(client_url=client.url)
