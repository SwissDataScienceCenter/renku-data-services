"""Adapters for repositories database classes."""

from collections.abc import Callable
from typing import Literal
from urllib.parse import urlparse

from authlib.integrations.httpx_client import OAuthError
from httpx import AsyncClient as HttpClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.app_config import logging
from renku_data_services.connected_services import orm as connected_services_schemas
from renku_data_services.connected_services.db import ConnectedServicesRepository
from renku_data_services.connected_services.utils import GitHubProviderType, get_github_provider_type
from renku_data_services.repositories import models
from renku_data_services.repositories.provider_adapters import (
    get_internal_gitlab_adapter,
    get_provider_adapter,
)

logger = logging.getLogger(__file__)


class GitRepositoriesRepository:
    """Repository for (git) repositories."""

    def __init__(
        self,
        session_maker: Callable[..., AsyncSession],
        connected_services_repo: ConnectedServicesRepository,
        internal_gitlab_url: str | None,
        enable_internal_gitlab: bool,
    ):
        self.session_maker = session_maker
        self.connected_services_repo = connected_services_repo
        self.internal_gitlab_url = internal_gitlab_url
        self.enable_internal_gitlab = enable_internal_gitlab

    def __include_repository_provider(self, c: connected_services_schemas.OAuth2ClientORM, repo_netloc: str) -> bool:
        github_type = get_github_provider_type(c)
        return urlparse(c.url).netloc == repo_netloc and (
            not github_type or github_type == GitHubProviderType.standard_app
        )

    async def get_repository(
        self,
        repository_url: str,
        user: base_models.APIUser,
        etag: str | None,
        internal_gitlab_user: base_models.APIUser,
    ) -> models.RepositoryProviderData | Literal["304"]:
        """Get the metadata about a repository."""
        repository_netloc = urlparse(repository_url).netloc

        async with self.session_maker() as session:
            result_clients = await session.scalars(select(connected_services_schemas.OAuth2ClientORM))
            clients = result_clients.all()

        matched_client = next(filter(lambda x: self.__include_repository_provider(x, repository_netloc), clients), None)
        logger.debug(
            f"Found oauth2 client '{matched_client.id if matched_client else None}' for repository '{repository_url}f'"
        )
        if matched_client is None:
            if self.enable_internal_gitlab and self.internal_gitlab_url:
                internal_gitlab_netloc = urlparse(self.internal_gitlab_url).netloc
                if internal_gitlab_netloc == repository_netloc:
                    return await self._get_repository_from_internal_gitlab(
                        repository_url=repository_url,
                        user=internal_gitlab_user,
                        etag=etag,
                        internal_gitlab_url=self.internal_gitlab_url,
                    )

            raise errors.MissingResourceError(message=f"No OAuth2 Client found for repository {repository_url}.")

        async with self.session_maker() as session:
            result = (
                await session.scalars(
                    select(connected_services_schemas.OAuth2ConnectionORM)
                    .where(connected_services_schemas.OAuth2ConnectionORM.client_id == matched_client.id)
                    .where(connected_services_schemas.OAuth2ConnectionORM.user_id == user.id)
                )
                if user.id is not None
                else None
            )
            connection = result.one_or_none() if result is not None else None

        logger.debug(
            f"Found connection '{connection.id if connection else None}' to access repository {repository_url}"
        )
        if connection is None:
            return await self._get_repository_anonymously(
                repository_url=repository_url, client=matched_client, etag=etag
            )
        authed_repo = await self._get_repository_authenticated(
            connection_id=connection.id, repository_url=repository_url, user=user, etag=etag
        )
        if authed_repo == "304":
            return "304"
        else:
            return models.RepositoryProviderData(
                connection=models.ProviderConnection(
                    id=connection.id, provider_id=matched_client.id, status=connection.status
                )
                if connection
                else None,
                provider=models.ProviderData(
                    id=matched_client.id, name=matched_client.display_name, url=matched_client.url
                ),
                repository_metadata=authed_repo.repository_metadata,
            )

    async def _get_repository_anonymously(
        self, repository_url: str, client: connected_services_schemas.OAuth2ClientORM, etag: str | None
    ) -> models.RepositoryProviderData | Literal["304"]:
        """Get the metadata about a repository without using credentials."""
        logger.debug(f"Get repository anonymousliy: {repository_url}")
        async with HttpClient(timeout=5) as http:
            adapter = get_provider_adapter(client)
            request_url = adapter.get_repository_api_url(repository_url)
            headers = adapter.api_common_headers or dict()
            if etag:
                headers["If-None-Match"] = etag
            response = await http.get(request_url, headers=headers)

            if response.status_code == 304:
                return "304"
            if response.status_code > 200:
                return models.RepositoryProviderData(
                    provider=models.ProviderData(id=client.id, name=client.display_name, url=client.url),
                    connection=None,
                    repository_metadata=None,
                )

            repository = adapter.api_validate_repository_response(response, is_anonymous=True)
            return models.RepositoryProviderData(
                provider=models.ProviderData(id=client.id, name=client.display_name, url=client.url),
                connection=None,
                repository_metadata=repository,
            )

    async def _get_repository_authenticated(
        self, connection_id: ULID, repository_url: str, user: base_models.APIUser, etag: str | None
    ) -> models.RepositoryProviderMatch | Literal["304"]:
        """Get the metadata about a repository using an OAuth2 connection."""
        logger.debug(f"Get repository with oauth2 '{connection_id}': {repository_url}")
        async with self.connected_services_repo.get_async_oauth2_client(connection_id=connection_id, user=user) as (
            oauth2_client,
            connection,
            _,
        ):
            adapter = get_provider_adapter(connection.client)
            request_url = adapter.get_repository_api_url(repository_url)
            headers = adapter.api_common_headers or dict()
            if etag:
                headers["If-None-Match"] = etag
            try:
                response = await oauth2_client.get(request_url, headers=headers)
            except OAuthError as err:
                if err.error == "bad_refresh_token":
                    raise errors.InvalidTokenError(
                        message="The refresh token for the repository has expired or is invalid.",
                        detail=f"Please reconnect your integration for {repository_url} and try again.",
                    ) from err
                raise

            if response.status_code == 304:
                return "304"
            if response.status_code > 200:
                return models.RepositoryProviderMatch(
                    provider_id=connection.client.id, connection_id=connection_id, repository_metadata=None
                )

            repository = adapter.api_validate_repository_response(response, is_anonymous=False)
            return models.RepositoryProviderMatch(
                provider_id=connection.client.id, connection_id=connection_id, repository_metadata=repository
            )

    async def _get_repository_from_internal_gitlab(
        self, repository_url: str, user: base_models.APIUser, etag: str | None, internal_gitlab_url: str
    ) -> models.RepositoryProviderData | Literal["304"]:
        """Get the metadata about a repository from the internal GitLab instance."""
        logger.debug(f"Get repository from internal gitlab: {repository_url}")
        async with HttpClient(timeout=5) as http:
            adapter = get_internal_gitlab_adapter(internal_gitlab_url)
            request_url = adapter.get_repository_api_url(repository_url)
            is_anonymous = not bool(user.access_token)
            headers = adapter.api_common_headers or dict()
            if user.access_token:
                headers["Authorization"] = f"Bearer {user.access_token}"
            if etag:
                headers["If-None-Match"] = etag
            response = await http.get(request_url, headers=headers)

            provider_data = models.ProviderData(id="INTERNAL_GITLAB", name="GitLab", url=self.internal_gitlab_url or "")
            if response.status_code == 304:
                return "304"
            if response.status_code > 200:
                return models.RepositoryProviderData(provider=provider_data, connection=None, repository_metadata=None)

            repository = adapter.api_validate_repository_response(response, is_anonymous=is_anonymous)
            return models.RepositoryProviderData(
                provider=provider_data, connection=None, repository_metadata=repository
            )
