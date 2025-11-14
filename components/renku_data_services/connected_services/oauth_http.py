"""Module wrapping an oauth library."""

import time
from base64 import b64decode, b64encode
from collections.abc import Callable, Coroutine
from enum import StrEnum
from typing import Any, Protocol
from urllib.parse import urljoin

import sqlalchemy as sa
import sqlalchemy.orm as sao
from authlib.integrations.base_client import InvalidTokenError, OAuthError
from authlib.integrations.httpx_client.oauth2_client import AsyncOAuth2Client
from httpx import URL, Response
from httpx._types import HeaderTypes, QueryParamTypes
from sqlalchemy.ext.asyncio.session import AsyncSession
from ulid import ULID

import renku_data_services.connected_services.orm as schemas
from renku_data_services.app_config import logging
from renku_data_services.base_api.pagination import PaginationRequest
from renku_data_services.connected_services import models
from renku_data_services.connected_services.orm import OAuth2ConnectionORM
from renku_data_services.connected_services.provider_adapters import (
    GitHubAdapter,
    ProviderAdapter,
    get_provider_adapter,
)
from renku_data_services.connected_services.utils import (
    GitHubProviderType,
    generate_code_verifier,
    get_github_provider_type,
)
from renku_data_services.errors import errors
from renku_data_services.users.db import APIUser
from renku_data_services.utils import cryptography as crypt

logger = logging.getLogger(__file__)


class OAuthHttpFactoryError(StrEnum):
    """Errors possible in this module."""

    invalid_connection = "invalid_connection"
    invalid_user = "invalid_user"
    no_client = "no_client"
    no_state = "no_state"


class OAuthHttpError(StrEnum):
    """Errors possible when using the client."""

    invalid_token = "invalid_token"  # nosec: B105
    unauthorized = "unauthorized"  # nosec: B105


class OAuthHttpClient(Protocol):
    """Http client injecting authorization tokens."""

    @property
    def connection(self) -> OAuth2ConnectionORM:
        """Return the associated connection."""
        ...

    async def get(
        self, url: URL | str, params: QueryParamTypes | None = None, headers: HeaderTypes | None = None
    ) -> Response:
        """Execute a get request."""
        ...

    async def get_connected_account(self) -> OAuthHttpError | models.ConnectedAccount:
        """Return the connected account."""
        ...

    async def get_token(self) -> models.OAuth2TokenSet:
        """Return the access token. This may involve refreshing the token and updating it."""
        ...

    async def get_oauth2_app_installations(
        self, pagination: PaginationRequest
    ) -> OAuthHttpError | models.AppInstallationList:
        """Gets the users app installations if available."""
        ...


class OAuthHttpClientFactory(Protocol):
    """Ways to create http-oauth clients."""

    async def for_user_connection(self, user: APIUser, connection_id: ULID) -> OAuthHttpFactoryError | OAuthHttpClient:
        """Create an oauth-http client for a given valid user and connection."""
        ...

    async def for_user_connection_raise(self, user: APIUser, connection_id: ULID) -> OAuthHttpClient:
        """Same as `for_user_connection` but throws on error."""
        ...

    async def initiate_oauth_flow(
        self, user: APIUser, provider_id: str, callback_url: str, next_url: str | None = None
    ) -> OAuthHttpFactoryError | str:
        """Create the authorization url to initiate the oauth flow.

        Creates a connection in the database or resets its status to 'pending'.
        """
        ...

    async def fetch_token(self, state: str, raw_url: str, callback_url: str) -> OAuthHttpFactoryError | OAuthHttpClient:
        """Finishes the flow by trying to obtain a token given the response url from the authorization challenge."""
        ...


class _TokenCrypt(Protocol):
    """Can encrypt/decrypt sensitive fields of the token set."""

    def encrypt_token_set(self, token: dict[str, Any], user_id: str) -> models.OAuth2TokenSet:
        """Encrypts sensitive fields of token set before persisting at rest."""
        ...

    def decrypt_token_set(self, token: dict[str, Any], user_id: str) -> models.OAuth2TokenSet:
        """Decrypts sensitive fields of token set."""
        ...


class _SafeAsyncOAuthClient(AsyncOAuth2Client):  # type: ignore  # nosec: B107
    def __init__(  # type: ignore # nosec: B105, B107
        self,
        client_id=None,
        client_secret=None,
        token_endpoint_auth_method=None,
        revocation_endpoint_auth_method=None,
        scope=None,
        redirect_uri=None,
        token=None,
        token_placement="header",  # nosec: B107
        update_token=None,
        leeway=60,
        **kwargs,
    ):
        super().__init__(
            client_id,
            client_secret,
            token_endpoint_auth_method,
            revocation_endpoint_auth_method,
            scope,
            redirect_uri,
            token,
            token_placement,
            update_token,
            leeway,
            **kwargs,
        )
        self._session_maker = kwargs["session_maker"]
        self._connection_id: ULID | None = kwargs.get("connection_id")
        self._token_crypt: _TokenCrypt = kwargs["token_crypt"]

    async def ensure_active_token(self, token):  # type: ignore
        try:
            return await super().ensure_active_token(token)
        except OAuthError as err:
            # This error comes from refreshing the access token. Each
            # oauth provider may present a different error code -
            # event thought the oauth spec
            # (https://www.rfc-editor.org/rfc/rfc6749#section-5.2) has
            # a list of what to return. For example, while tests with
            # GitLab gives errors exactly copied from the spec
            # ("invalid_grant"), GitHub presents a "bad_refresh_token"
            # error code. After all, we can never know. From the
            # implementation of AsyncOAuth2Client this error is always
            # only from trying to obtain a new access token.
            #
            # Here we try to detect a stale read. If that is the case,
            # we can hack the new token into this client and proceed
            # to execute the request. This works only, because we are
            # called right before the request is send and how
            # AsyncOAuthClient is implemented 😇
            logger.info(f"OAuth error while refreshing the token: {err}.")
            if not self._connection_id:
                logger.warning("No connection id set to check for an recently updated token!")
            else:
                logger.info(f"Looking up current connection {self._connection_id} for recent updates.")
                async with self._session_maker() as session:
                    result = await session.scalars(
                        sa.select(schemas.OAuth2ConnectionORM).where(
                            schemas.OAuth2ConnectionORM.id == self._connection_id
                        )
                    )
                    conn = result.one_or_none()
                if conn is None or conn.token is None:
                    logger.debug(f"No valid connection found for id: {self._connection_id}")
                    raise
                else:
                    now = time.time()
                    expires_at: float | None = self.token.get("expires_at")  # type: ignore
                    # if the connection has been updated after current expiry date
                    newer_than_expiry = expires_at and expires_at < conn.updated_at.timestamp()
                    # if it has been updated recently (a fallback when no expiry date exists)
                    pretty_recent = now - self.leeway < conn.updated_at.timestamp()
                    if newer_than_expiry or pretty_recent:
                        logger.info(
                            f"Retrying with recently updated token ({now - conn.updated_at.timestamp():.1f}s ago)."
                        )
                        self.token = self._token_crypt.decrypt_token_set(conn.token, conn.user_id)
                    else:
                        logger.info(
                            f"The connection token in the database hasn't been updated since {conn.updated_at}. "
                            "The user needs to run through the oauth flow again to re-connect."
                        )
                        raise errors.InvalidTokenError(
                            message="The refresh token for the connected service has expired or is invalid.",
                            detail=f"Please reconnect your integration for the service with ID {str(conn.id)} "
                            "and try again.",
                        ) from err


class DefaultOAuthClient(OAuthHttpClient):
    """The default oauth-http client."""

    def __init__(self, delegate: AsyncOAuth2Client, connection: OAuth2ConnectionORM, adapter: ProviderAdapter) -> None:
        self._delegate = delegate
        self.adapter = adapter
        self._connection = connection

    @property
    def connection(self) -> OAuth2ConnectionORM:
        """Return the associated connection."""
        return self._connection

    async def get_connected_account(self) -> OAuthHttpError | models.ConnectedAccount:
        """Get the connected account."""
        request_url = urljoin(self.adapter.api_url, self.adapter.user_info_endpoint)
        try:
            if self.adapter.user_info_method == "POST":
                response = await self._delegate.post(request_url, headers=self.adapter.api_common_headers)
            else:
                response = await self.get(request_url, headers=self.adapter.api_common_headers)
        except InvalidTokenError as e:
            logger.info(f"Invalid token for connection={self.connection.id}: {e}", exc_info=e)
            return OAuthHttpError.invalid_token

        if response.status_code > 200:
            logger.info(
                f"Error response {response.status_code} from user-info endpoint "
                "for connection={self.connection.id}: {response.text}"
            )
            return OAuthHttpError.unauthorized

        account = self.adapter.api_validate_account_response(response)
        return account

    async def get(
        self, url: URL | str, params: QueryParamTypes | None = None, headers: HeaderTypes | None = None
    ) -> Response:
        """Execute a get request."""
        resp: Response = await self._delegate.get(url, params=params, headers=headers)
        return resp

    async def get_token(self) -> models.OAuth2TokenSet:
        """Return the access token."""
        await self._delegate.ensure_active_token(self._delegate.token)
        token_model = models.OAuth2TokenSet.from_dict(self._delegate.token)
        return token_model

    async def get_oauth2_app_installations(
        self, pagination: PaginationRequest
    ) -> OAuthHttpError | models.AppInstallationList:
        """Gets the users app installations if available."""
        # NOTE: App installations are only available from GitHub when using a "GitHub App"
        if (
            self.connection.client.kind == models.ProviderKind.github
            and get_github_provider_type(self.connection.client) == GitHubProviderType.standard_app
            and isinstance(self.adapter, GitHubAdapter)
        ):
            request_url = urljoin(self.adapter.api_url, "user/installations")
            params = dict(page=pagination.page, per_page=pagination.per_page)
            response = await self.get(request_url, params=params, headers=self.adapter.api_common_headers)

            if response.status_code > 200:
                logger.warning(
                    f"Could not get installations at {request_url}: {response.status_code} - {response.text}"
                )
                return OAuthHttpError.unauthorized

            return self.adapter.api_validate_app_installations_response(response)

        return models.AppInstallationList(total_count=0, installations=[])


class DefaultOAuthHttpClientFactory(OAuthHttpClientFactory, _TokenCrypt):
    """Default variant for creating oauth-http clients."""

    def __init__(self, encryption_key: bytes, session_maker: Callable[..., AsyncSession]) -> None:
        self._encryption_key = encryption_key
        self._session_maker = session_maker

    async def for_user_connection_raise(self, user: APIUser, connection_id: ULID) -> OAuthHttpClient:
        """Same as `for_user_connection` but throws on error."""
        client = await self.for_user_connection(user, connection_id)
        match client:
            case OAuthHttpFactoryError() as err:
                logger.info(f"Error getting oauth client for user={user.id} conn={connection_id}: {err}")
                raise errors.ForbiddenError(message="You don't have the required permissions to perform this operation")
            case _:
                return client

    async def for_user_connection(self, user: APIUser, connection_id: ULID) -> OAuthHttpFactoryError | OAuthHttpClient:
        """Create an oauth-http client for the given user and connection."""
        if not user.is_authenticated or user.id is None:
            return OAuthHttpFactoryError.invalid_user

        async with self._session_maker() as session:
            result = await session.scalars(
                sa.select(schemas.OAuth2ConnectionORM)
                .where(schemas.OAuth2ConnectionORM.id == connection_id)
                .where(schemas.OAuth2ConnectionORM.user_id == user.id)
                .where(schemas.OAuth2ConnectionORM.token.is_not(None))
                .where(schemas.OAuth2ConnectionORM.status == models.ConnectionStatus.connected)
                .options(sao.selectinload(schemas.OAuth2ConnectionORM.client))
            )
            connection = result.one_or_none()
            if connection is None or connection.token is None:
                logger.debug(f"No valid connection found for connection: {connection_id}")
                return OAuthHttpFactoryError.invalid_connection

            client = connection.client
            token = self.decrypt_token_set(token=connection.token, user_id=user.id)

        adapter = get_provider_adapter(client)
        client_secret = (
            crypt.decrypt_string(self._encryption_key, client.created_by_id, client.client_secret)
            if client.client_secret
            else None
        )
        code_verifier = connection.code_verifier
        code_challenge_method = "S256" if code_verifier else None

        retval: OAuthHttpClient = DefaultOAuthClient(
            _SafeAsyncOAuthClient(
                client_id=client.client_id,
                client_secret=client_secret,
                scope=client.scope,
                code_challenge_method=code_challenge_method,
                token_endpoint=adapter.token_endpoint_url,
                token=token,
                update_token=self._update_token(connection),
                session_maker=self._session_maker,
                connection_id=connection_id,
                token_crypt=self,
            ),
            connection,
            adapter,
        )
        return retval

    async def initiate_oauth_flow(
        self, user: APIUser, provider_id: str, callback_url: str, next_url: str | None = None
    ) -> OAuthHttpFactoryError | str:
        """Create the authorization url to initiate the oauth flow."""
        if not user.is_authenticated or user.id is None:
            return OAuthHttpFactoryError.invalid_user

        async with self._session_maker() as session, session.begin():
            result = await session.scalars(
                sa.select(schemas.OAuth2ClientORM).where(schemas.OAuth2ClientORM.id == provider_id)
            )
            client = result.one_or_none()
            if client is None:
                return OAuthHttpFactoryError.no_client

            adapter = get_provider_adapter(client)
            client_secret = (
                crypt.decrypt_string(self._encryption_key, client.created_by_id, client.client_secret)
                if client.client_secret
                else None
            )
            code_verifier = generate_code_verifier() if client.use_pkce else None
            code_challenge_method = "S256" if client.use_pkce else None
            oauth_client = _SafeAsyncOAuthClient(
                client_id=client.client_id,
                client_secret=client_secret,
                redirect_uri=callback_url,
                scope=client.scope,
                code_challenge_method=code_challenge_method,
                token_endpoint=adapter.token_endpoint_url,
                session_maker=self._session_maker,
                token_crypt=self,
            )
            url: str
            state: str
            url, state = oauth_client.create_authorization_url(
                adapter.authorization_url, code_verifier=code_verifier, **adapter.authorization_url_extra_params
            )

            result_conn = await session.scalars(
                sa.select(schemas.OAuth2ConnectionORM)
                .where(schemas.OAuth2ConnectionORM.client_id == client.id)
                .where(schemas.OAuth2ConnectionORM.user_id == user.id)
            )
            connection = result_conn.one_or_none()

            if connection is None:
                connection = schemas.OAuth2ConnectionORM(
                    user_id=user.id,
                    client_id=client.id,
                    token=None,
                    state=state,
                    status=models.ConnectionStatus.pending,
                    code_verifier=code_verifier,
                    next_url=next_url,
                )
                session.add(connection)
            else:
                connection.state = state
                connection.status = models.ConnectionStatus.pending
                connection.code_verifier = code_verifier
                connection.next_url = next_url

            await session.flush()
            await session.refresh(connection)

        return url

    async def fetch_token(self, state: str, raw_url: str, callback_url: str) -> OAuthHttpFactoryError | OAuthHttpClient:
        """Finishes the flow by trying to obtain a token given the response url from the authorization challenge."""
        if not state:
            logger.info("fetch_token called without a state")
            return OAuthHttpFactoryError.no_state

        async with self._session_maker() as session, session.begin():
            result = await session.scalars(
                sa.select(schemas.OAuth2ConnectionORM)
                .where(schemas.OAuth2ConnectionORM.state == state)
                .options(sao.selectinload(schemas.OAuth2ConnectionORM.client))
            )
            connection = result.one_or_none()

            if connection is None:
                logger.debug(f"No connection found for state {state}")
                return OAuthHttpFactoryError.invalid_connection

            client = connection.client
            adapter = get_provider_adapter(client)
            client_secret = (
                crypt.decrypt_string(self._encryption_key, client.created_by_id, client.client_secret)
                if client.client_secret
                else None
            )
            code_verifier = connection.code_verifier
            code_challenge_method = "S256" if code_verifier else None
            oauth_client = _SafeAsyncOAuthClient(
                client_id=client.client_id,
                client_secret=client_secret,
                scope=client.scope,
                redirect_uri=callback_url,
                code_challenge_method=code_challenge_method,
                state=connection.state,
                session_maker=self._session_maker,
                connection_id=connection.id,
                token_crypt=self,
            )
            token = await oauth_client.fetch_token(
                adapter.token_endpoint_url, authorization_response=raw_url, code_verifier=code_verifier
            )

            logger.info(f"Token for client {client.id} has keys: {', '.join(token.keys())}")

            next_url = connection.next_url
            connection.token = self.encrypt_token_set(token=token, user_id=connection.user_id)
            connection.state = None
            connection.status = models.ConnectionStatus.connected
            connection.next_url = None

        connection.next_url = next_url
        retval: OAuthHttpClient = DefaultOAuthClient(
            _SafeAsyncOAuthClient(
                client_id=client.client_id,
                client_secret=client_secret,
                redirect_uri=callback_url,
                scope=client.scope,
                code_challenge_method=code_challenge_method,
                token_endpoint=adapter.token_endpoint_url,
                token=token,
                update_token=self._update_token(connection),
                session_maker=self._session_maker,
                connection_id=connection.id,
                token_crypt=self,
            ),
            connection,
            adapter,
        )
        return retval

    def _update_token(
        self, connection: OAuth2ConnectionORM
    ) -> Callable[[dict[str, Any], str | None], Coroutine[Any, Any, None]]:
        async def _update_fn(token: dict[str, Any], refresh_token: str | None = None) -> None:
            if refresh_token is None:
                return
            async with self._session_maker() as session, session.begin():
                session.add(connection)
                await session.refresh(connection)
                connection.token = self.encrypt_token_set(token=token, user_id=connection.user_id)
                await session.flush()
                await session.refresh(connection)
                logger.info("Token refreshed!")

        return _update_fn

    def encrypt_token_set(self, token: dict[str, Any], user_id: str) -> models.OAuth2TokenSet:
        """Encrypts sensitive fields of token set before persisting at rest."""
        result = models.OAuth2TokenSet.from_dict(token)
        if result.access_token:
            result["access_token"] = b64encode(
                crypt.encrypt_string(self._encryption_key, user_id, result.access_token)
            ).decode("ascii")
        if result.refresh_token:
            result["refresh_token"] = b64encode(
                crypt.encrypt_string(self._encryption_key, user_id, result.refresh_token)
            ).decode("ascii")
        return result

    def decrypt_token_set(self, token: dict[str, Any], user_id: str) -> models.OAuth2TokenSet:
        """Decrypts sensitive fields of token set."""
        result = models.OAuth2TokenSet.from_dict(token)
        if result.access_token:
            result["access_token"] = crypt.decrypt_string(self._encryption_key, user_id, b64decode(result.access_token))
        if result.refresh_token:
            result["refresh_token"] = crypt.decrypt_string(
                self._encryption_key, user_id, b64decode(result.refresh_token)
            )
        return result
