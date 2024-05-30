"""Adapters for each kind of OAuth2 client."""

from abc import ABC, abstractmethod
from datetime import datetime
from urllib.parse import quote, urljoin, urlparse, urlunparse

from httpx import Response
from sanic.log import logger

from renku_data_services import errors
from renku_data_services.connected_services import external_models, models
from renku_data_services.connected_services import orm as schemas
from renku_data_services.connected_services.apispec import ProviderKind


class ProviderAdapter(ABC):
    """Defines the functionality of OAuth2 client adapters."""

    def __init__(self, client: schemas.OAuth2ClientORM) -> None:
        if not client.url:
            raise errors.ValidationError(message=f"URL not defined for provider {client.id}.")
        self.client = client

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

    @abstractmethod
    def get_repository_api_url(self, repository_url: str) -> str:
        """Compute the metadata API URL for a git repository."""
        ...

    @abstractmethod
    def api_validate_repository_response(
        self, response: Response, is_anonymous: bool = False
    ) -> models.RepositoryMetadata:
        """Validates and returns the connected account response from the Resource Server."""
        ...


class GitLabAdapter(ProviderAdapter):
    """Adapter for GitLab OAuth2 clients."""

    @property
    def authorization_url(self) -> str:
        """The authorization URL for the OAuth2 protocol."""
        return urljoin(self.client.url, "oauth/authorize")

    @property
    def token_endpoint_url(self) -> str:
        """The token endpoint URL for the OAuth2 protocol."""
        return urljoin(self.client.url, "oauth/token")

    @property
    def api_url(self) -> str:
        """The URL used for API calls on the Resource Server."""
        return urljoin(self.client.url, "api/v4/")

    def api_validate_account_response(self, response: Response) -> models.ConnectedAccount:
        """Validates and returns the connected account response from the Resource Server."""
        return external_models.GitLabConnectedAccount.model_validate(response.json()).to_connected_account()

    def get_repository_api_url(self, repository_url: str) -> str:
        """Compute the metadata API URL for a git repository."""
        path = urlparse(repository_url).path
        path = path.removeprefix("/").removesuffix(".git")
        return urljoin(self.api_url, f"projects/{quote(path, safe="")}")

    def api_validate_repository_response(
        self, response: Response, is_anonymous: bool = False
    ) -> models.RepositoryMetadata:
        """Validates and returns the connected account response from the Resource Server."""
        model = external_models.GitLabRepository.model_validate(response.json())
        logger.info(f"Got gitlab data: {model}")
        new_etag = response.headers.get("ETag")
        return model.to_repository(
            etag=new_etag,
            # NOTE: we assume the "pull" permission if a GitLab repository is publicly visible
            default_permissions=models.RepositoryPermissions(pull=True, push=False) if is_anonymous else None,
        )


class GitHubAdapter(ProviderAdapter):
    """Adapter for GitLab OAuth2 clients."""

    @property
    def authorization_url(self) -> str:
        """The authorization URL for the OAuth2 protocol."""
        return urljoin(self.client.url, "login/oauth/authorize")

    @property
    def token_endpoint_url(self) -> str:
        """The token endpoint URL for the OAuth2 protocol."""
        return urljoin(self.client.url, "login/oauth/access_token")

    @property
    def api_url(self) -> str:
        """The URL used for API calls on the Resource Server."""
        url = urlparse(self.client.url)
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

    def get_repository_api_url(self, repository_url: str) -> str:
        """Compute the metadata API URL for a git repository."""
        path = urlparse(repository_url).path
        path = path.removeprefix("/").removesuffix(".git")
        return urljoin(self.api_url, f"repos/{path}")

    def api_validate_repository_response(
        self, response: Response, is_anonymous: bool = False
    ) -> models.RepositoryMetadata:
        """Validates and returns the connected account response from the Resource Server."""
        model = external_models.GitHubRepository.model_validate(response.json())
        logger.info(f"Got github data: {model}")
        new_etag = response.headers.get("ETag")
        return model.to_repository(
            etag=new_etag,
            # NOTE: we assume the "pull" permission if a GitLab repository is publicly visible
            default_permissions=models.RepositoryPermissions(pull=True, push=False) if is_anonymous else None,
        )


_adapter_map: dict[ProviderKind, type[ProviderAdapter]] = {
    ProviderKind.gitlab: GitLabAdapter,
    ProviderKind.github: GitHubAdapter,
}


def get_provider_adapter(client: schemas.OAuth2ClientORM) -> ProviderAdapter:
    """Returns a new ProviderAdapter instance corresponding to the given client."""
    global _adapter_map

    adapter_class = _adapter_map[client.kind]
    return adapter_class(client=client)


def get_internal_gitlab_adapter(internal_gitlab_url: str):
    """Returns an adapter instance corresponding to the internal GitLab provider."""
    client = schemas.OAuth2ClientORM(
        id="INTERNAL_GITLAB",
        client_id="INTERNAL_GITLAB",
        display_name="INTERNAL_GITLAB",
        created_by_id="",
        kind=ProviderKind.gitlab,
        scope="",
        url=internal_gitlab_url,
        use_pkce=False,
        client_secret=None,
        creation_date=datetime.now(),
        updated_at=datetime.now(),
    )
    return GitLabAdapter(client)
