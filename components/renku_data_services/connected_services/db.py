"""Adapters for connected services database classes."""

from base64 import b64decode, b64encode
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from typing import Any, cast
from urllib.parse import urljoin

from authlib.integrations.base_client import InvalidTokenError
from authlib.integrations.httpx_client import AsyncOAuth2Client
from sanic.log import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from ulid import ULID

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.connected_services import apispec, models
from renku_data_services.connected_services import orm as schemas
from renku_data_services.connected_services.apispec import ConnectionStatus
from renku_data_services.connected_services.provider_adapters import (
    ProviderAdapter,
    get_provider_adapter,
)
from renku_data_services.connected_services.utils import generate_code_verifier
from renku_data_services.utils.cryptography import decrypt_string, encrypt_string


class ConnectedServicesRepository:
    """Repository for connected services."""

    def __init__(
        self,
        session_maker: Callable[..., AsyncSession],
        encryption_key: bytes,
        async_oauth2_client_class: type[AsyncOAuth2Client],
        internal_gitlab_url: str | None,
    ):
        self.session_maker = session_maker
        self.encryption_key = encryption_key
        self.async_oauth2_client_class = async_oauth2_client_class
        self.internal_gitlab_url = internal_gitlab_url.rstrip("/") if internal_gitlab_url else None

    async def get_oauth2_clients(
        self,
        user: base_models.APIUser,
    ) -> list[models.OAuth2Client]:
        """Get all OAuth2 Clients from the database."""
        async with self.session_maker() as session:
            result = await session.scalars(select(schemas.OAuth2ClientORM))
            clients = result.all()
            return [c.dump(user_is_admin=user.is_admin) for c in clients]

    async def get_oauth2_client(self, provider_id: str, user: base_models.APIUser) -> models.OAuth2Client:
        """Get one OAuth2 Client from the database."""
        async with self.session_maker() as session:
            result = await session.scalars(
                select(schemas.OAuth2ClientORM).where(schemas.OAuth2ClientORM.id == provider_id)
            )
            client = result.one_or_none()
            if client is None:
                raise errors.MissingResourceError(
                    message=f"OAuth2 Client with id '{provider_id}' does not exist or you do not have access to it."  # noqa: E501
                )
            return client.dump(user_is_admin=user.is_admin)

    async def insert_oauth2_client(
        self,
        user: base_models.APIUser,
        new_client: apispec.ProviderPost,
    ) -> models.OAuth2Client:
        """Insert a new OAuth2 Client environment."""
        if user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")
        if not user.is_admin:
            raise errors.ForbiddenError(message="You do not have the required permissions for this operation.")

        encrypted_client_secret = (
            encrypt_string(self.encryption_key, user.id, new_client.client_secret) if new_client.client_secret else None
        )
        client = schemas.OAuth2ClientORM(
            id=new_client.id,
            kind=new_client.kind,
            client_id=new_client.client_id,
            client_secret=encrypted_client_secret,
            display_name=new_client.display_name,
            scope=new_client.scope,
            url=new_client.url,
            use_pkce=new_client.use_pkce or False,
            created_by_id=user.id,
        )

        async with self.session_maker() as session, session.begin():
            result = await session.scalars(
                select(schemas.OAuth2ClientORM).where(schemas.OAuth2ClientORM.id == client.id)
            )
            existing_client = result.one_or_none()
            if existing_client is not None:
                raise errors.ValidationError(message=f"OAuth2 Client with id '{client.id}' already exists.")

            session.add(client)
            await session.flush()
            await session.refresh(client)
            return client.dump(user_is_admin=user.is_admin)

    async def update_oauth2_client(
        self, user: base_models.APIUser, provider_id: str, **kwargs: dict
    ) -> models.OAuth2Client:
        """Update an OAuth2 Client entry."""
        if not user.is_admin:
            raise errors.ForbiddenError(message="You do not have the required permissions for this operation.")

        async with self.session_maker() as session, session.begin():
            result = await session.scalars(
                select(schemas.OAuth2ClientORM).where(schemas.OAuth2ClientORM.id == provider_id)
            )
            client = result.one_or_none()
            if client is None:
                raise errors.MissingResourceError(message=f"OAuth2 Client with id '{provider_id}' does not exist.")

            client_secret = cast(str | None, kwargs.get("client_secret"))
            if client_secret:
                client.client_secret = encrypt_string(
                    self.encryption_key, client.created_by_id, cast(str, kwargs["client_secret"])
                )
            elif client_secret == "":  # nosec B105
                client.client_secret = None

            for key, value in kwargs.items():
                if key in ["kind", "client_id", "display_name", "scope", "url", "use_pkce"]:
                    setattr(client, key, value)

            await session.flush()
            await session.refresh(client)

            return client.dump(user_is_admin=user.is_admin)

    async def delete_oauth2_client(self, user: base_models.APIUser, provider_id: str) -> None:
        """Delete an OAuth2 Client."""
        if not user.is_admin:
            raise errors.ForbiddenError(message="You do not have the required permissions for this operation.")

        async with self.session_maker() as session, session.begin():
            result = await session.scalars(
                select(schemas.OAuth2ClientORM).where(schemas.OAuth2ClientORM.id == provider_id)
            )
            client = result.one_or_none()

            if client is None:
                return

            await session.delete(client)

    async def authorize_client(
        self, user: base_models.APIUser, provider_id: str, callback_url: str, next_url: str | None = None
    ) -> str:
        """Authorize an OAuth2 Client."""
        if not user.is_authenticated or user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")

        async with self.session_maker() as session, session.begin():
            result = await session.scalars(
                select(schemas.OAuth2ClientORM).where(schemas.OAuth2ClientORM.id == provider_id)
            )
            client = result.one_or_none()

            if client is None:
                raise errors.MissingResourceError(message=f"OAuth2 Client with id '{provider_id}' does not exist.")

            adapter = get_provider_adapter(client)
            client_secret = (
                decrypt_string(self.encryption_key, client.created_by_id, client.client_secret)
                if client.client_secret
                else None
            )
            code_verifier = generate_code_verifier() if client.use_pkce else None
            code_challenge_method = "S256" if client.use_pkce else None
            async with self.async_oauth2_client_class(
                client_id=client.client_id,
                client_secret=client_secret,
                scope=client.scope,
                redirect_uri=callback_url,
                code_challenge_method=code_challenge_method,
            ) as oauth2_client:
                url: str
                state: str
                url, state = oauth2_client.create_authorization_url(
                    adapter.authorization_url, code_verifier=code_verifier, **adapter.authorization_url_extra_params
                )

                result_conn = await session.scalars(
                    select(schemas.OAuth2ConnectionORM)
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
                        status=schemas.ConnectionStatus.pending,
                        code_verifier=code_verifier,
                        next_url=next_url,
                    )
                    session.add(connection)
                else:
                    connection.state = state
                    connection.status = schemas.ConnectionStatus.pending
                    connection.code_verifier = code_verifier
                    connection.next_url = next_url

                await session.flush()
                await session.refresh(connection)

                return url

    async def authorize_callback(self, state: str, raw_url: str, callback_url: str) -> str | None:
        """Performs the OAuth2 authorization callback.

        Returns the `next_url` parameter value the authorization flow was started with.
        """
        if not state:
            raise errors.ForbiddenError(message="You do not have the required permissions for this operation.")

        async with self.session_maker() as session, session.begin():
            result = await session.scalars(
                select(schemas.OAuth2ConnectionORM)
                .where(schemas.OAuth2ConnectionORM.state == state)
                .options(selectinload(schemas.OAuth2ConnectionORM.client))
            )
            connection = result.one_or_none()

            if connection is None:
                raise errors.ForbiddenError(message="You do not have the required permissions for this operation.")

            client = connection.client
            adapter = get_provider_adapter(client)
            client_secret = (
                decrypt_string(self.encryption_key, client.created_by_id, client.client_secret)
                if client.client_secret
                else None
            )
            code_verifier = connection.code_verifier
            code_challenge_method = "S256" if code_verifier else None
            async with self.async_oauth2_client_class(
                client_id=client.client_id,
                client_secret=client_secret,
                scope=client.scope,
                redirect_uri=callback_url,
                code_challenge_method=code_challenge_method,
                state=connection.state,
            ) as oauth2_client:
                token = await oauth2_client.fetch_token(
                    adapter.token_endpoint_url, authorization_response=raw_url, code_verifier=code_verifier
                )

                logger.info(f"Token for client {client.id} has keys: {", ".join(token.keys())}")

                next_url = connection.next_url

                connection.token = self._encrypt_token_set(token=token, user_id=connection.user_id)
                connection.state = None
                connection.status = schemas.ConnectionStatus.connected
                connection.next_url = None

                return next_url

    async def get_oauth2_connections(
        self,
        user: base_models.APIUser,
    ) -> list[models.OAuth2Connection]:
        """Get all OAuth2 connections for the user from the database."""
        if not user.is_authenticated or user.id is None:
            return []

        async with self.session_maker() as session:
            result = await session.scalars(
                select(schemas.OAuth2ConnectionORM).where(schemas.OAuth2ConnectionORM.user_id == user.id)
            )
            connections = result.all()
            return [c.dump() for c in connections]

    async def get_oauth2_connection(self, connection_id: ULID, user: base_models.APIUser) -> models.OAuth2Connection:
        """Get one OAuth2 connection from the database."""
        if not user.is_authenticated or user.id is None:
            raise errors.MissingResourceError(
                message=f"OAuth2 connection with id '{connection_id}' does not exist or you do not have access to it."  # noqa: E501
            )

        async with self.session_maker() as session:
            result = await session.scalars(
                select(schemas.OAuth2ConnectionORM)
                .where(schemas.OAuth2ConnectionORM.id == connection_id)
                .where(schemas.OAuth2ConnectionORM.user_id == user.id)
            )
            connection = result.one_or_none()
            if connection is None:
                raise errors.MissingResourceError(
                    message=f"OAuth2 connection with id '{connection_id}' does not exist or you do not have access to it."  # noqa: E501
                )
            return connection.dump()

    async def get_oauth2_connected_account(
        self, connection_id: ULID, user: base_models.APIUser
    ) -> models.ConnectedAccount:
        """Get the account information from a OAuth2 connection."""
        async with self.get_async_oauth2_client(connection_id=connection_id, user=user) as (oauth2_client, _, adapter):
            request_url = urljoin(adapter.api_url, adapter.user_info_endpoint)
            try:
                if adapter.user_info_method == "POST":
                    response = await oauth2_client.post(request_url, headers=adapter.api_common_headers)
                else:
                    response = await oauth2_client.get(request_url, headers=adapter.api_common_headers)
            except InvalidTokenError as e:
                raise errors.InvalidOAuth2Token() from e

            if response.status_code > 200:
                raise errors.UnauthorizedError(message=f"Could not get account information.{response.json()}")

            account = adapter.api_validate_account_response(response)
            return account

    async def get_oauth2_connection_token(
        self, connection_id: ULID, user: base_models.APIUser
    ) -> models.OAuth2TokenSet:
        """Get the OAuth2 access token from one connection from the database."""
        async with self.get_async_oauth2_client(connection_id=connection_id, user=user) as (oauth2_client, _, _):
            await oauth2_client.ensure_active_token(oauth2_client.token)
            token_model = models.OAuth2TokenSet.from_dict(oauth2_client.token)
            return token_model

    @asynccontextmanager
    async def get_async_oauth2_client(
        self, connection_id: ULID, user: base_models.APIUser
    ) -> AsyncGenerator[tuple[AsyncOAuth2Client, schemas.OAuth2ConnectionORM, ProviderAdapter], None]:
        """Get the AsyncOAuth2Client for the given connection_id and user."""
        if not user.is_authenticated or user.id is None:
            raise errors.MissingResourceError(
                message=f"OAuth2 connection with id '{connection_id}' does not exist or you do not have access to it."  # noqa: E501
            )

        async with self.session_maker() as session:
            result = await session.scalars(
                select(schemas.OAuth2ConnectionORM)
                .where(schemas.OAuth2ConnectionORM.id == connection_id)
                .where(schemas.OAuth2ConnectionORM.user_id == user.id)
                .options(selectinload(schemas.OAuth2ConnectionORM.client))
            )
            connection = result.one_or_none()
            if connection is None:
                raise errors.MissingResourceError(
                    message=f"OAuth2 connection with id '{connection_id}' does not exist or you do not have access to it."  # noqa: E501
                )

            if connection.status != ConnectionStatus.connected or connection.token is None:
                raise errors.UnauthorizedError(message=f"OAuth2 connection with id '{connection_id}' is not valid.")

            client = connection.client
            token = self._decrypt_token_set(token=connection.token, user_id=user.id)

        async def update_token(token: dict[str, Any], refresh_token: str | None = None) -> None:
            if refresh_token is None:
                return
            async with self.session_maker() as session, session.begin():
                session.add(connection)
                await session.refresh(connection)
                connection.token = self._encrypt_token_set(token=token, user_id=connection.user_id)
                await session.flush()
                await session.refresh(connection)
                logger.info("Token refreshed!")

        adapter = get_provider_adapter(client)
        client_secret = (
            decrypt_string(self.encryption_key, client.created_by_id, client.client_secret)
            if client.client_secret
            else None
        )
        code_verifier = connection.code_verifier
        code_challenge_method = "S256" if code_verifier else None
        yield (
            self.async_oauth2_client_class(
                client_id=client.client_id,
                client_secret=client_secret,
                scope=client.scope,
                code_challenge_method=code_challenge_method,
                token_endpoint=adapter.token_endpoint_url,
                token=token,
                update_token=update_token,
            ),
            connection,
            adapter,
        )

    def _encrypt_token_set(self, token: dict[str, Any], user_id: str) -> models.OAuth2TokenSet:
        """Encrypts sensitive fields of token set before persisting at rest."""
        result = models.OAuth2TokenSet.from_dict(token)
        if result.access_token:
            result["access_token"] = b64encode(
                encrypt_string(self.encryption_key, user_id, result.access_token)
            ).decode("ascii")
        if result.refresh_token:
            result["refresh_token"] = b64encode(
                encrypt_string(self.encryption_key, user_id, result.refresh_token)
            ).decode("ascii")
        return result

    def _decrypt_token_set(self, token: dict[str, Any], user_id: str) -> models.OAuth2TokenSet:
        """Encrypts sensitive fields of token set before persisting at rest."""
        result = models.OAuth2TokenSet.from_dict(token)
        if result.access_token:
            result["access_token"] = decrypt_string(self.encryption_key, user_id, b64decode(result.access_token))
        if result.refresh_token:
            result["refresh_token"] = decrypt_string(self.encryption_key, user_id, b64decode(result.refresh_token))
        return result
