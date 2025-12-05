"""Adapters for each kind of OAuth2 client."""

from abc import ABC, abstractmethod
from urllib.parse import quote, urljoin, urlparse, urlunparse

from httpx import Response

from renku_data_services import errors
from renku_data_services.app_config import logging
from renku_data_services.connected_services import models as connected_services_models
from renku_data_services.connected_services.models import ProviderKind
from renku_data_services.repositories import external_models, models

logger = logging.getLogger(__name__)


class GitProviderAdapter(ABC):
    """Defines the functionality of git providers adapters."""

    def __init__(self, client_url: str) -> None:
        self.client_url = client_url

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
    def get_repository_api_url(self, repository_url: str) -> str:
        """Compute the metadata API URL for a git repository."""
        ...

    @abstractmethod
    def api_validate_repository_response(
        self, response: Response, is_anonymous: bool = False
    ) -> models.RepositoryMetadata:
        """Validates and returns the connected account response from the Resource Server."""
        ...


class GitLabAdapter(GitProviderAdapter):
    """Adapter for GitLab OAuth2 clients."""

    @property
    def api_url(self) -> str:
        """The URL used for API calls on the Resource Server."""
        return urljoin(self.client_url, "api/v4/")

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


class GitHubAdapter(GitProviderAdapter):
    """Adapter for GitHub OAuth2 clients."""

    @property
    def api_url(self) -> str:
        """The URL used for API calls on the Resource Server."""
        url = urlparse(self.client_url)
        # See: https://docs.github.com/en/apps/sharing-github-apps/making-your-github-app-available-for-github-enterprise-server#the-app-code-must-use-the-correct-urls
        if url.netloc != "github.com":
            return urljoin(self.client_url, "api/v3/")
        url = url._replace(netloc=f"api.{url.netloc}")
        return urlunparse(url)

    @property
    def api_common_headers(self) -> dict[str, str] | None:
        """The HTTP headers used for API calls on the Resource Server."""
        return {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

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


_adapter_map: dict[ProviderKind, type[GitProviderAdapter]] = {
    ProviderKind.gitlab: GitLabAdapter,
    ProviderKind.github: GitHubAdapter,
}


def get_provider_adapter(client: connected_services_models.OAuth2Client) -> GitProviderAdapter:
    """Returns a new GitProviderAdapter instance corresponding to the give OAuth2 client."""
    global _adapter_map

    if not client.url:
        raise errors.ValidationError(message=f"URL not defined for provider {client.id}.")

    adapter_class = _adapter_map[client.kind]
    return adapter_class(client_url=client.url)


def get_internal_gitlab_adapter(internal_gitlab_url: str) -> GitLabAdapter:
    """Returns an adapter instance corresponding to the internal GitLab provider."""
    client_url = internal_gitlab_url
    return GitLabAdapter(client_url=client_url)
