"""Adapters for connected services database classes."""

import base64
import json
import random
from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode, urljoin

from authlib.integrations.httpx_client import AsyncOAuth2Client
from sanic.log import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.connected_services import apispec, models
from renku_data_services.connected_services import orm as schemas


class ConnectedServicesRepository:
    """Repository for connected services."""

    def __init__(self, session_maker: Callable[..., AsyncSession]):
        self.session_maker = session_maker  # type: ignore[call-overload]

    async def get_oauth2_clients(
        self,
        user: base_models.APIUser,
    ) -> list[models.OAuth2Client]:
        """Get all OAuth2 Clients from the database."""
        async with self.session_maker() as session:
            redacted = not user.is_admin

            result = await session.scalars(select(schemas.OAuth2ClientORM))
            clients = result.all()

            return [c.dump(redacted=redacted) for c in clients]

    async def get_oauth2_client(self, provider_id: str, user: base_models.APIUser) -> models.OAuth2Client:
        """Get one OAuth2 Client from the database."""
        async with self.session_maker() as session:
            redacted = not user.is_admin

            result = await session.scalars(
                select(schemas.OAuth2ClientORM).where(schemas.OAuth2ClientORM.id == provider_id)
            )
            client = result.one_or_none()
            if client is None:
                raise errors.MissingResourceError(
                    message=f"OAuth2 Client with id '{provider_id}' does not exist or you do not have access to it."  # noqa: E501
                )
            return client.dump(redacted=redacted)

    async def insert_oauth2_client(
        self,
        user: base_models.APIUser,
        new_client: apispec.AdminProviderPost,
    ) -> models.OAuth2Client:
        """Insert a new OAuth2 Client environment."""
        if user.id is None or not user.is_admin:
            raise errors.Unauthorized(message="You do not have the required permissions for this operation.")

        client = schemas.OAuth2ClientORM(
            id=new_client.id,
            kind=new_client.kind,
            client_id=new_client.client_id,
            client_secret=new_client.client_secret if new_client.client_secret else None,
            display_name=new_client.display_name,
            scope=new_client.scope,
            url=new_client.url,
            created_by_id=user.id,
        )

        async with self.session_maker() as session, session.begin():
            session.add(client)
            await session.flush()
            await session.refresh(client)
            return client.dump(redacted=False)

    async def update_oauth2_client(self, user: base_models.APIUser, provider_id: str, **kwargs) -> models.OAuth2Client:
        """Update an OAuth2 Client entry."""
        if not user.is_admin:
            raise errors.Unauthorized(message="You do not have the required permissions for this operation.")

        async with self.session_maker() as session, session.begin():
            result = await session.scalars(
                select(schemas.OAuth2ClientORM).where(schemas.OAuth2ClientORM.id == provider_id)
            )
            client = result.one_or_none()
            if client is None:
                raise errors.MissingResourceError(message=f"OAuth2 Client with id '{provider_id}' does not exist.")

            for key, value in kwargs.items():
                if key in ["kind", "client_id", "client_secret", "display_name", "scope", "url"]:
                    setattr(client, key, value)

            await session.flush()
            await session.refresh(client)

            return client.dump(redacted=False)

    async def delete_oauth2_client(self, user: base_models.APIUser, provider_id: str) -> None:
        """Delete an OAuth2 Client."""
        if not user.is_admin:
            raise errors.Unauthorized(message="You do not have the required permissions for this operation.")

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
    ) -> tuple[str, str]:
        """Authorize an OAuth2 Client."""
        if not user.is_authenticated or user.id is None:
            raise errors.Unauthorized(message="You do not have the required permissions for this operation.")

        async with self.session_maker() as session, session.begin():
            result = await session.scalars(
                select(schemas.OAuth2ClientORM).where(schemas.OAuth2ClientORM.id == provider_id)
            )
            client = result.one_or_none()

            if client is None:
                raise errors.MissingResourceError(message=f"OAuth2 Client with id '{provider_id}' does not exist.")

            if next_url:
                query = urlencode([("next", next_url)])
                callback_url = f"{callback_url}?{query}"

            async with AsyncOAuth2Client(
                client_id=client.client_id,
                client_secret=client.client_secret,
                scope=client.scope,
                redirect_uri=callback_url,
            ) as oauth2_client:
                url, state = oauth2_client.create_authorization_url(client.authorization_url)

                cookie = _generate_cookie()

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
                        cookie=cookie,
                        state=state,
                        status=schemas.ConnectionStatus.pending,
                    )
                    session.add(connection)
                else:
                    connection.cookie = cookie
                    connection.state = state
                    connection.status = schemas.ConnectionStatus.pending

                await session.flush()
                await session.refresh(connection)

                return url, cookie

    async def authorize_callback(
        self, cookie: str, raw_url: str, callback_url: str, next_url: str | None = None
    ) -> dict | Any:
        """Performs the OAuth2 authorization callback."""
        if not cookie:
            raise errors.Unauthorized(message="You do not have the required permissions for this operation.")

        async with self.session_maker() as session, session.begin():
            result = await session.scalars(
                select(schemas.OAuth2ConnectionORM)
                .where(schemas.OAuth2ConnectionORM.cookie == cookie)
                .options(selectinload(schemas.OAuth2ConnectionORM.client))
            )
            connection = result.one_or_none()

            if connection is None:
                raise errors.Unauthorized(message="You do not have the required permissions for this operation.")

            if next_url:
                query = urlencode([("next", next_url)])
                callback_url = f"{callback_url}?{query}"

            client = connection.client
            async with AsyncOAuth2Client(
                client_id=client.client_id,
                client_secret=client.client_secret,
                scope=client.scope,
                redirect_uri=callback_url,
                state=connection.state,
            ) as oauth2_client:
                token = await oauth2_client.fetch_token(client.token_endpoint_url, authorization_response=raw_url)

                logger.info(f"Token for client {client.id} has keys: {", ".join(token.keys())}")

                token_model = models.OAuth2TokenSet.from_dict(token)
                connection.token = json.dumps(token_model.to_dict())
                connection.cookie = None
                connection.state = None
                connection.status = schemas.ConnectionStatus.connected

                await session.flush()
                await session.refresh(connection)

                return token

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

    async def get_oauth2_connection(self, connection_id: str, user: base_models.APIUser) -> models.OAuth2Connection:
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
        self, connection_id: str, user: base_models.APIUser
    ) -> models.ConnectedAccount:
        """Get the account information from a OAuth2 connection."""
        if not user.is_authenticated or user.id is None:
            raise errors.MissingResourceError(
                message=f"OAuth2 connection with id '{connection_id}' does not exist or you do not have access to it."  # noqa: E501
            )

        async with self.session_maker() as session, session.begin():
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

            if connection.token is None:
                raise errors.Unauthorized(message=f"OAuth2 connection with id '{connection_id}' is not valid.")

            client = connection.client
            token = models.OAuth2TokenSet.from_dict(json.loads(connection.token))
            async with AsyncOAuth2Client(
                client_id=client.client_id,
                client_secret=client.client_secret,
                scope=client.scope,
                token_endpoint=client.token_endpoint_url,
            ) as oauth2_client:
                oauth2_client.token = token.to_dict()

                await oauth2_client.ensure_active_token(oauth2_client.token)
                token_model = models.OAuth2TokenSet.from_dict(oauth2_client.token)
                old_token = connection.token
                connection.token = json.dumps(token_model.to_dict())

                if old_token != connection.token:
                    logger.info("Token refreshed!")

                await session.flush()
                await session.refresh(connection)

                # TODO: how to configure this?
                request_url = urljoin(client.url, "api/v4/user")
                response = await oauth2_client.get(request_url)

                if response.status_code > 200:
                    raise errors.Unauthorized(message="Could not get account information.")

                account = models.ConnectedAccount.model_validate(response.json())
                return account

    async def get_oauth2_connection_token(self, connection_id: str, user: base_models.APIUser) -> models.OAuth2TokenSet:
        """Get the OAuth2 access token from one connection from the database."""
        if not user.is_authenticated or user.id is None:
            raise errors.MissingResourceError(
                message=f"OAuth2 connection with id '{connection_id}' does not exist or you do not have access to it."  # noqa: E501
            )

        async with self.session_maker() as session, session.begin():
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

            if connection.token is None:
                raise errors.Unauthorized(message=f"OAuth2 connection with id '{connection_id}' is not valid.")

            client = connection.client
            token = models.OAuth2TokenSet.from_dict(json.loads(connection.token))
            async with AsyncOAuth2Client(
                client_id=client.client_id,
                client_secret=client.client_secret,
                scope=client.scope,
                token_endpoint=client.token_endpoint_url,
            ) as oauth2_client:
                oauth2_client.token = token.to_dict()

                await oauth2_client.ensure_active_token(oauth2_client.token)
                token_model = models.OAuth2TokenSet.from_dict(oauth2_client.token)
                old_token = connection.token
                connection.token = json.dumps(token_model.to_dict())

                if old_token != connection.token:
                    logger.info("Token refreshed!")

                await session.flush()
                await session.refresh(connection)

                return token_model


def _generate_cookie():
    rand = random.SystemRandom()
    return base64.b64encode(rand.randbytes(32)).decode()
