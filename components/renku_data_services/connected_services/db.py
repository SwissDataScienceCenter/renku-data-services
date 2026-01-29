"""Adapters for connected services database classes."""

from collections.abc import Callable
from urllib.parse import urlparse

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from ulid import ULID

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.app_config import logging
from renku_data_services.connected_services import models
from renku_data_services.connected_services import orm as schemas
from renku_data_services.connected_services.oauth_http import (
    OAuthHttpClientFactory,
    OAuthHttpFactoryError,
)
from renku_data_services.notebooks.api.classes.image import Image, ImageRepoDockerAPI
from renku_data_services.users.db import APIUser
from renku_data_services.utils.cryptography import encrypt_string

logger = logging.getLogger(__name__)


class ConnectedServicesRepository:
    """Repository for connected services."""

    def __init__(
        self,
        session_maker: Callable[..., AsyncSession],
        oauth_client_factory: OAuthHttpClientFactory,
        encryption_key: bytes,
    ):
        self.session_maker = session_maker
        self.encryption_key = encryption_key
        self.oauth_client_factory = oauth_client_factory
        self.supported_image_registry_providers = {models.ProviderKind.gitlab, models.ProviderKind.github}

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
                    message=f"OAuth2 Client with id '{provider_id}' does not exist or you do not have access to it."
                )
            return client.dump(user_is_admin=user.is_admin)

    async def insert_oauth2_client(
        self, user: base_models.APIUser, new_client: models.UnsavedOAuth2Client
    ) -> models.OAuth2Client:
        """Insert a new OAuth2 Client environment."""
        if user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")
        if not user.is_admin:
            raise errors.ForbiddenError(message="You do not have the required permissions for this operation.")

        provider_id = base_models.Slug.from_name(new_client.id).value
        encrypted_client_secret = (
            encrypt_string(self.encryption_key, user.id, new_client.client_secret) if new_client.client_secret else None
        )
        client = schemas.OAuth2ClientORM(
            id=provider_id,
            kind=new_client.kind,
            app_slug=new_client.app_slug or "",
            client_id=new_client.client_id,
            client_secret=encrypted_client_secret,
            display_name=new_client.display_name,
            scope=new_client.scope,
            url=new_client.url,
            use_pkce=new_client.use_pkce or False,
            created_by_id=user.id,
            image_registry_url=new_client.image_registry_url,
            oidc_issuer_url=new_client.oidc_issuer_url or None,
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
        self,
        user: base_models.APIUser,
        provider_id: str,
        patch: models.OAuth2ClientPatch,
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

            if patch.kind is not None:
                client.kind = patch.kind
            if patch.app_slug is not None:
                client.app_slug = patch.app_slug
            if patch.client_id is not None:
                client.client_id = patch.client_id
            if patch.client_secret:
                client.client_secret = encrypt_string(self.encryption_key, client.created_by_id, patch.client_secret)
            elif patch.client_secret == "":  # nosec B105
                client.client_secret = None
            if patch.display_name is not None:
                client.display_name = patch.display_name
            if patch.scope is not None:
                client.scope = patch.scope
            if patch.url is not None:
                client.url = patch.url
            if patch.use_pkce is not None:
                client.use_pkce = patch.use_pkce
            if patch.image_registry_url:
                # Patching with a string of at least length 1 updates the value
                client.image_registry_url = patch.image_registry_url
            elif patch.image_registry_url == "":
                # Patching with "", removes the value
                client.image_registry_url = None
            if patch.oidc_issuer_url:
                client.oidc_issuer_url = patch.oidc_issuer_url
            elif patch.oidc_issuer_url == "":
                client.oidc_issuer_url = None
            # Unset oidc_issuer_url when the kind has been changed to a value other than 'generic_oidc'
            if client.kind != models.ProviderKind.generic_oidc:
                client.oidc_issuer_url = None

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

    async def delete_oauth2_connection(self, user: base_models.APIUser, connection_id: ULID) -> bool:
        """Delete one connection of the given user."""
        if not user.is_authenticated or user.id is None:
            return False

        async with self.session_maker() as session, session.begin():
            result = await session.scalars(
                select(schemas.OAuth2ConnectionORM)
                .where(schemas.OAuth2ConnectionORM.id == connection_id)
                .where(schemas.OAuth2ConnectionORM.user_id == user.id)
            )
            conn = result.one_or_none()

            if conn is None:
                return False

            await session.delete(conn)
            return True

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

    async def get_oauth2_connection_or_none(
        self, connection_id: ULID, user: base_models.APIUser
    ) -> models.OAuth2Connection | None:
        """Get one OAuth2 connection from the database. Throw if the user is not authenticated."""
        if not user.is_authenticated or user.id is None:
            raise errors.MissingResourceError(
                message=f"OAuth2 connection with id '{connection_id}' does not exist or you do not have access to it."
            )

        async with self.session_maker() as session:
            result = await session.scalars(
                select(schemas.OAuth2ConnectionORM)
                .where(schemas.OAuth2ConnectionORM.id == connection_id)
                .where(schemas.OAuth2ConnectionORM.user_id == user.id)
            )
            connection = result.one_or_none()
            if connection:
                return connection.dump()
            else:
                return None

    async def get_oauth2_connection(self, connection_id: ULID, user: base_models.APIUser) -> models.OAuth2Connection:
        """Get one OAuth2 connection from the database.

        Throw if the connection doesn't exist or the user is not authenticated.
        """
        connection = await self.get_oauth2_connection_or_none(connection_id, user)
        if connection is None:
            raise errors.MissingResourceError(
                message=f"OAuth2 connection with id '{connection_id}' does not exist or you do not have access to it."
            )

        return connection

    async def get_provider_for_image(self, user: APIUser, image: Image) -> models.ImageProvider | None:
        """Find a provider supporting the given image."""
        registry_urls = [f"http://{image.hostname}", f"https://{image.hostname}"]
        async with self.session_maker() as session:
            stmt = (
                select(schemas.OAuth2ClientORM, schemas.OAuth2ConnectionORM)
                .join(
                    schemas.OAuth2ConnectionORM,
                    and_(
                        schemas.OAuth2ConnectionORM.client_id == schemas.OAuth2ClientORM.id,
                        schemas.OAuth2ConnectionORM.user_id == user.id,
                    ),
                    isouter=True,  # isouter makes it a left-join, not an outer join
                )
                .where(schemas.OAuth2ClientORM.image_registry_url.in_(registry_urls))
                .where(schemas.OAuth2ClientORM.kind.in_(self.supported_image_registry_providers))
                # there could be multiple matching - just take the first arbitrary 🤷
                .order_by(schemas.OAuth2ConnectionORM.updated_at.desc())
                .limit(1)
            )
            result = await session.execute(stmt)
            row = result.one_or_none()
            if row is None or row.OAuth2ClientORM is None:
                return None
            else:
                return models.ImageProvider(
                    row.OAuth2ClientORM.dump(),
                    models.ConnectedUser(row.OAuth2ConnectionORM.dump(), user)
                    if row.OAuth2ConnectionORM is not None
                    else None,
                    str(row.OAuth2ClientORM.image_registry_url),  # above query makes it non-nil
                )

    async def get_provider_for_kind(
        self, user: APIUser, provider_kind: models.ProviderKind
    ) -> models.ServiceProvider | None:
        """Find a service provider of a given kind."""
        async with self.session_maker() as session:
            # First, match an established connection if it exists
            stmt = (
                select(schemas.OAuth2ConnectionORM)
                .join(schemas.OAuth2ClientORM)
                .where(schemas.OAuth2ConnectionORM.user_id == user.id)
                .where(schemas.OAuth2ConnectionORM.status == models.ConnectionStatus.connected.value)
                .where(schemas.OAuth2ClientORM.kind == provider_kind.value)
                .options(selectinload(schemas.OAuth2ConnectionORM.client))
                .limit(1)
            )
            res = await session.scalars(stmt)
            connection = res.one_or_none()
            if connection is not None:
                return models.ServiceProvider(
                    provider=connection.client.dump(),
                    connected_user=models.ConnectedUser(connection=connection.dump(), user=user),
                )
            # Otherwise, match the first suitable provider
            provider_stmt = (
                select(schemas.OAuth2ClientORM).where(schemas.OAuth2ClientORM.kind == provider_kind.value).limit(1)
            )
            provider_res = await session.scalars(provider_stmt)
            provider = provider_res.one_or_none()
            if provider is not None:
                return models.ServiceProvider(
                    provider=provider.dump(),
                    connected_user=None,
                )
            return None

    async def get_token_set(self, user: APIUser, connection_id: ULID) -> models.OAuth2TokenSet | None:
        """Returns the token set from a given OAuth2 connection."""
        client_or_error = await self.oauth_client_factory.for_user_connection(user=user, connection_id=connection_id)
        match client_or_error:
            case OAuthHttpFactoryError() as err:
                logger.info(f"Error getting oauth client for user={user} connection={connection_id}: {err}")
                return None
            case client:
                return await client.get_token()

    async def get_image_repo_client(self, image_provider: models.ImageProvider) -> ImageRepoDockerAPI:
        """Create a image repository client for the given user and image provider."""
        url = urlparse(image_provider.registry_url)
        repo_api = ImageRepoDockerAPI(hostname=url.netloc, scheme=url.scheme)
        if image_provider.is_connected():
            assert image_provider.connected_user is not None
            user = image_provider.connected_user.user
            conn = image_provider.connected_user.connection
            access_token: str | None = None
            token_set = await self.get_token_set(user=user, connection_id=conn.id)
            if token_set is not None:
                access_token = token_set.access_token
            if access_token:
                logger.debug(f"Use connection {conn.id} to {image_provider.provider.id} for user {user.id}")
                repo_api = repo_api.with_oauth2_token(access_token)
        return repo_api
