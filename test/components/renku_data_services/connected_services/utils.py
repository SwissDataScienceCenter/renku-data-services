from collections.abc import Callable
from typing import override

from authlib.integrations.httpx_client.oauth2_client import AsyncOAuth2Client
from httpx import URL, Response
from httpx._types import HeaderTypes, QueryParamTypes
from sqlalchemy.ext.asyncio.session import AsyncSession

import renku_data_services.connected_services.models as models
from renku_data_services.base_api.pagination import PaginationRequest
from renku_data_services.connected_services.oauth_http import (
    DefaultOAuthHttpClientFactory,
    OAuthHttpClient,
    OAuthHttpError,
)
from renku_data_services.connected_services.orm import OAuth2ConnectionORM
from renku_data_services.connected_services.provider_adapters import ProviderAdapter


class FixedTestOAuthHttpClient(OAuthHttpClient):
    def __init__(
        self,
        response: Response | None = None,
        account: models.ConnectedAccount | OAuthHttpError | None = None,
        token: models.OAuth2TokenSet | None = None,
        apps: models.AppInstallationList | OAuthHttpError | None = None,
        client: models.OAuth2Client | None = None,
    ) -> None:
        self.response = response
        self.account = account
        self.token = token
        self.apps = apps
        self._client = client

    @property
    def client(self) -> models.OAuth2Client:
        if self._client:
            return self._client
        raise Exception("not implemented")

    @property
    def connection(self) -> models.OAuth2Connection:
        raise Exception("not implemented")

    async def get(
        self, url: URL | str, params: QueryParamTypes | None = None, headers: HeaderTypes | None = None
    ) -> Response:
        if self.response:
            return self.response
        raise Exception("not implemented")

    async def get_connected_account(self) -> OAuthHttpError | models.ConnectedAccount:
        if self.account:
            return self.account
        raise Exception("not implemented")

    async def get_token(self) -> models.OAuth2TokenSet:
        if self.token:
            return self.token
        raise Exception("not implemented")

    async def get_oauth2_app_installations(
        self, pagination: PaginationRequest
    ) -> OAuthHttpError | models.AppInstallationList:
        if self.apps:
            return self.apps
        raise Exception("not implemented")


class FixedOAuthHttpClientFactory(DefaultOAuthHttpClientFactory):
    def __init__(
        self, encryption_key: bytes, session_maker: Callable[..., AsyncSession], client: OAuthHttpClient
    ) -> None:
        super().__init__(encryption_key, session_maker)
        self.client = client

    @override
    def create_http_client(
        self, delegate: AsyncOAuth2Client, connection: OAuth2ConnectionORM, adapter: ProviderAdapter
    ) -> OAuthHttpClient:
        return self.client
