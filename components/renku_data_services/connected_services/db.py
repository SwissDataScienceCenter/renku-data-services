"""Adapters for connected services database classes."""

from collections.abc import Callable
from typing import Any

from authlib.integrations.httpx_client import AsyncOAuth2Client
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.connected_services import apispec, models
from renku_data_services.connected_services import orm as schemas


class ConnectedServicesRepository:
    """Repository for connected services."""

    _authorization_url = "https://gitlab.com/oauth/authorize"
    _callback_url = "https://renku-ci-ds-179.dev.renku.ch/ui-server/api/data/oauth2/callback"
    _scope = "api"

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
            client_id=new_client.client_id,
            client_secret=new_client.client_secret if new_client.client_secret else None,
            display_name=new_client.display_name,
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
                if key in ["client_id", "client_secret", "display_name"]:
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

    async def authorize_client(self, user: base_models.APIUser, provider_id: str) -> tuple[str, str | Any]:
        """Authorize an OAuth2 Client."""
        if not user.is_authenticated or user.id is None:
            raise errors.Unauthorized(message="You do not have the required permissions for this operation.")

        async with self.session_maker() as session:
            result = await session.scalars(
                select(schemas.OAuth2ClientORM).where(schemas.OAuth2ClientORM.id == provider_id)
            )
            client = result.one_or_none()

            if client is None:
                raise errors.MissingResourceError(message=f"OAuth2 Client with id '{provider_id}' does not exist.")

            oauth2_client = AsyncOAuth2Client(
                client_id=client.client_id,
                client_secret=client.client_secret,
                scope=self._scope,
                redirect_uri=self._callback_url,
            )
            authorization_endpoint = self._authorization_url
            url, state = oauth2_client.create_authorization_url(authorization_endpoint)
            return url, state
