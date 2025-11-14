"""Adapters for repositories database classes."""

from collections.abc import Callable
from typing import Literal
from urllib.parse import urlparse

import pydantic
from authlib.integrations.httpx_client import OAuthError
from httpx import AsyncClient as HttpClient
from httpx import Response, TransportError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

import renku_data_services.base_models as base_models
from renku_data_services.app_config import logging
from renku_data_services.base_models.core import APIUser
from renku_data_services.connected_services import orm as connected_services_schemas
from renku_data_services.connected_services.db import ConnectedServicesRepository
from renku_data_services.connected_services.models import ConnectionStatus
from renku_data_services.connected_services.oauth_http import OAuthHttpClientFactory
from renku_data_services.connected_services.utils import GitHubProviderType, get_github_provider_type
from renku_data_services.repositories import models
from renku_data_services.repositories.git_url import GitUrl, GitUrlError
from renku_data_services.repositories.provider_adapters import (
    GitProviderAdapter,
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
        oauth_client_factory: OAuthHttpClientFactory,
        internal_gitlab_url: str | None,
        enable_internal_gitlab: bool,
        httpClient: HttpClient | None = None,
    ):
        self.session_maker = session_maker
        self.connected_services_repo = connected_services_repo
        self.oauth_client_factory = oauth_client_factory
        self.internal_gitlab_url = internal_gitlab_url
        self.enable_internal_gitlab = enable_internal_gitlab
        self.httpClient = httpClient if httpClient else HttpClient(timeout=5)

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
    ) -> models.RepositoryDataResult:
        """Get metadata about one repository."""
        match GitUrl.parse(repository_url):
            case GitUrlError() as err:
                return models.RepositoryDataResult(error=err)
            case url:
                valid_url = url
                result = models.RepositoryDataResult()

        provider = await self._find_client(valid_url)
        connection = await self._find_connection(user, provider) if provider else None
        result = result.with_provider_orm(provider).with_connection_orm(connection)
        if provider:
            repo_meta = (
                await self._get_repository_authenticated_or_anonym(
                    connection_id=connection.id, client=provider, repository_url=valid_url, user=user, etag=etag
                )
                if connection and connection.status == ConnectionStatus.connected
                else await self._get_repository_anonymously(repository_url=valid_url, client=provider, etag=etag)
            )
            result = result.with_metadata(repo_meta)

        else:
            if self._is_internal_gitlab(valid_url) and self.internal_gitlab_url:
                provider_data = models.ProviderData(id="INTERNAL_GITLAB", name="GitLab", url=self.internal_gitlab_url)
                repo_meta = await self._get_repository_from_internal_gitlab(
                    repository_url=valid_url,
                    user=internal_gitlab_user,
                    etag=etag,
                    internal_gitlab_url=self.internal_gitlab_url,
                )
                result = result.with_metadata(repo_meta).with_provider(provider_data)

        if not result.metadata:
            repo_err = await self._check_arbitrary_git_repo(valid_url)
            # don't overwrite previous errors
            result = result.with_error(repo_err) if not result.error else result
            if repo_err is None:
                result = result.with_metadata(models.Metadata(git_url=valid_url.render(), pull_permission=True))

        return result

    async def _check_arbitrary_git_repo(self, url: GitUrl) -> models.RepositoryError | None:
        if url.parsed_url.netloc == "localhost":
            return models.RepositoryMetadataError.metadata_unknown
        return await url.check_http_git_repository(self.httpClient)

    async def _find_connection(
        self, user: APIUser, client: connected_services_schemas.OAuth2ClientORM
    ) -> connected_services_schemas.OAuth2ConnectionORM | None:
        async with self.session_maker() as session:
            result = (
                await session.scalars(
                    select(connected_services_schemas.OAuth2ConnectionORM)
                    .where(connected_services_schemas.OAuth2ConnectionORM.client_id == client.id)
                    .where(connected_services_schemas.OAuth2ConnectionORM.user_id == user.id)
                )
                if user.id is not None
                else None
            )
            conn = result.one_or_none() if result is not None else None
            logger.debug(f"Found connection {conn.id if conn else None} for client {client.id} and user {user.id}")
            return conn

    async def _find_client(self, url: GitUrl) -> connected_services_schemas.OAuth2ClientORM | None:
        async with self.session_maker() as session:
            result_clients = await session.scalars(select(connected_services_schemas.OAuth2ClientORM))
            clients = result_clients.all()

        matched_client = next(
            filter(lambda x: self.__include_repository_provider(x, url.parsed_url.netloc), clients), None
        )
        logger.debug(f"Found oauth2 client '{matched_client.id if matched_client else None}' for repository '{url}'")
        return matched_client

    def _is_internal_gitlab(self, url: GitUrl) -> bool:
        if self.enable_internal_gitlab and self.internal_gitlab_url:
            internal_gitlab_netloc = urlparse(self.internal_gitlab_url).netloc
            return internal_gitlab_netloc == url.parsed_url.netloc
        return False

    def _convert_metadata_response(
        self, adapter: GitProviderAdapter, response: Response
    ) -> models.RepositoryMetadata | models.RepositoryMetadataError | Literal["304"]:
        if response.status_code == 304:
            return "304"
        if response.status_code == 401:
            return models.RepositoryMetadataError.metadata_unauthorized
        if response.status_code > 200:
            trailingMsg = "."
            if response._request:
                trailingMsg = f": {response.request.url}"
            logger.error(f"Error status {response.status_code} returned for repository metadata{trailingMsg}")
            return models.RepositoryMetadataError.metadata_unknown

        try:
            return adapter.api_validate_repository_response(response, is_anonymous=True)
        except pydantic.ValidationError as err:
            logger.error(f"Error decoding response from provider adapter '{adapter}': {err}")
            return models.RepositoryMetadataError.metadata_validation

    async def _get_repository_anonymously(
        self, repository_url: GitUrl, client: connected_services_schemas.OAuth2ClientORM, etag: str | None
    ) -> models.RepositoryMetadata | models.RepositoryMetadataError | Literal["304"]:
        """Get the metadata about a repository without using credentials."""
        logger.debug(f"Get repository anonymousliy: {repository_url}")
        adapter = get_provider_adapter(client)
        request_url = adapter.get_repository_api_url(repository_url.render())
        headers = adapter.api_common_headers or dict()
        if etag:
            headers["If-None-Match"] = etag
        try:
            response = await self.httpClient.get(request_url, headers=headers)
            return self._convert_metadata_response(adapter, response)
        except TransportError as err:
            logger.debug(f"Error accessing url for git repo check ({err}): {request_url}")
            return models.RepositoryMetadataError.metadata_unknown

    async def _get_repository_authenticated(
        self, connection_id: ULID, repository_url: GitUrl, user: base_models.APIUser, etag: str | None
    ) -> models.RepositoryMetadata | Literal["304"] | models.RepositoryMetadataError:
        """Get the metadata about a repository using an OAuth2 connection."""
        logger.debug(f"Get repository with oauth2 '{connection_id}': {repository_url}")
        oauth_client = await self.oauth_client_factory.for_user_connection_raise(user, connection_id)
        adapter = get_provider_adapter(oauth_client.connection.client)
        request_url = adapter.get_repository_api_url(repository_url.render())
        headers = adapter.api_common_headers or dict()
        if etag:
            headers["If-None-Match"] = etag
        try:
            response = await oauth_client.get(request_url, headers=headers)
        except OAuthError as err:
            logger.warning(f"OAuth error accessing repository metadata: {err}", exc_info=err)
            return models.RepositoryMetadataError.metadata_oauth

        return self._convert_metadata_response(adapter, response)

    async def _get_repository_authenticated_or_anonym(
        self,
        connection_id: ULID,
        client: connected_services_schemas.OAuth2ClientORM,
        repository_url: GitUrl,
        user: base_models.APIUser,
        etag: str | None,
    ) -> models.RepositoryMetadata | Literal["304"] | models.RepositoryMetadataError:
        result = await self._get_repository_authenticated(connection_id, repository_url, user, etag)
        match result:
            case models.RepositoryMetadata() as md:
                return md
            case "304":
                return "304"
            case models.RepositoryMetadataError() as err:
                if err == models.RepositoryMetadataError.metadata_validation:
                    return err
                else:
                    logger.info(f"Got error {err} when getting repo metadata with auth. Trying anonymously.")
                    anon_result = await self._get_repository_anonymously(repository_url, client, etag)
                    match anon_result:
                        case models.RepositoryMetadataError() as anon_err:
                            logger.info(f"Got error {anon_err} when trying anonmyously. Return original error")
                            return err
                        case _:
                            return anon_result

    async def _get_repository_from_internal_gitlab(
        self, repository_url: GitUrl, user: base_models.APIUser, etag: str | None, internal_gitlab_url: str
    ) -> models.RepositoryMetadata | Literal["304"] | models.RepositoryMetadataError:
        """Get the metadata about a repository from the internal GitLab instance."""
        logger.debug(f"Get repository from internal gitlab: {repository_url}")
        adapter = get_internal_gitlab_adapter(internal_gitlab_url)
        request_url = adapter.get_repository_api_url(repository_url.render())
        headers = adapter.api_common_headers or dict()
        if user.access_token:
            headers["Authorization"] = f"Bearer {user.access_token}"
        if etag:
            headers["If-None-Match"] = etag
        try:
            response = await self.httpClient.get(request_url, headers=headers)
            return self._convert_metadata_response(adapter, response)
        except TransportError as err:
            logger.debug(f"Error accessing url for git repo check ({err}): {request_url}")
            return models.RepositoryMetadataError.metadata_unknown
