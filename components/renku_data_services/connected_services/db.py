"""Adapters for connected services database classes."""
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
            client_id=new_client.clientId,
            display_name=new_client.displayName,
            created_by_id=user.id,
        )

        async with self.session_maker() as session, session.begin():
            session.add(client)
            return client.dump(redacted=False)
