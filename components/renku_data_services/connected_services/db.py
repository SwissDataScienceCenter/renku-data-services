"""Adapters for connected services database classes."""

from base64 import b64decode, b64encode
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urljoin, urlparse

from authlib.integrations.base_client import InvalidTokenError
from authlib.integrations.httpx_client import AsyncOAuth2Client, OAuthError
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from ulid import ULID

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.app_config import logging
from renku_data_services.base_api.pagination import PaginationRequest
from renku_data_services.connected_services import models
from renku_data_services.connected_services import orm as schemas
from renku_data_services.connected_services.provider_adapters import (
    GitHubAdapter,
    ProviderAdapter,
    get_provider_adapter,
)
from renku_data_services.connected_services.utils import generate_code_verifier
from renku_data_services.notebooks.api.classes.image import Image, ImageRepoDockerAPI
from renku_data_services.users.db import APIUser
from renku_data_services.utils.cryptography import decrypt_string, encrypt_string

logger = logging.getLogger(__name__)


class ConnectedServicesRepository:
    """Repository for connected services."""

    def __init__(
        self,
        session_maker: Callable[..., AsyncSession],
        encryption_key: bytes,
        async_oauth2_client_class: type[AsyncOAuth2Client],
    ):
        self.session_maker = session_maker
        self.encryption_key = encryption_key
        self.async_oauth2_client_class = async_oauth2_client_class
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

                logger.info(f"Token for client {client.id} has keys: {', '.join(token.keys())}")

                next_url = connection.next_url

                connection.token = self._encrypt_token_set(token=token, user_id=connection.user_id)
                connection.state = None
                connection.status = models.ConnectionStatus.connected
                connection.next_url = None

                return next_url

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
                raise errors.UnauthorizedError(message="OAuth2 token for connected service invalid or expired.") from e

            if response.status_code > 200:
                raise errors.UnauthorizedError(message=f"Could not get account information.{response.json()}")

            account = adapter.api_validate_account_response(response)
            return account

    async def get_oauth2_connection_token(
        self, connection_id: ULID, user: base_models.APIUser
    ) -> models.OAuth2TokenSet:
        """Get the OAuth2 access token from one connection from the database."""
        async with self.get_async_oauth2_client(connection_id=connection_id, user=user) as (oauth2_client, _, _):
            try:
                await oauth2_client.ensure_active_token(oauth2_client.token)
            except OAuthError as err:
                if err.error == "bad_refresh_token":
                    raise errors.InvalidTokenError(
                        message="The refresh token for the connected service has expired or is invalid.",
                        detail=f"Please reconnect your integration for the service with ID {str(connection_id)} "
                        "and try again.",
                    ) from err
                raise
            token_model = models.OAuth2TokenSet.from_dict(oauth2_client.token)
            return token_model

    async def get_provider_for_image(self, user: APIUser, image: Image) -> models.ImageProvider | None:
        """Find a provider supporting the given an image."""
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

    async def get_image_repo_client(self, image_provider: models.ImageProvider) -> ImageRepoDockerAPI:
        """Create a image repository client for the given user and image provider."""
        url = urlparse(image_provider.registry_url)
        repo_api = ImageRepoDockerAPI(hostname=url.netloc, scheme=url.scheme)
        if image_provider.is_connected():
            assert image_provider.connected_user is not None
            user = image_provider.connected_user.user
            conn = image_provider.connected_user.connection
            token_set = await self.get_oauth2_connection_token(conn.id, user)
            access_token = token_set.access_token
            if access_token:
                logger.debug(f"Use connection {conn.id} to {image_provider.provider.id} for user {user.id}")
                repo_api = repo_api.with_oauth2_token(access_token)
        return repo_api

    async def get_oauth2_app_installations(
        self, connection_id: ULID, user: base_models.APIUser, pagination: PaginationRequest
    ) -> models.AppInstallationList:
        """Get the installations from a OAuth2 connection."""
        async with self.get_async_oauth2_client(connection_id=connection_id, user=user) as (
            oauth2_client,
            connection,
            adapter,
        ):
            # NOTE: App installations are only available from GitHub
            if connection.client.kind == models.ProviderKind.github and isinstance(adapter, GitHubAdapter):
                request_url = urljoin(adapter.api_url, "user/installations")
                params = dict(page=pagination.page, per_page=pagination.per_page)
                try:
                    response = await oauth2_client.get(request_url, params=params, headers=adapter.api_common_headers)
                except OAuthError as err:
                    if err.error == "bad_refresh_token":
                        raise errors.InvalidTokenError(
                            message="The refresh token for the connected service has expired or is invalid.",
                            detail=f"Please reconnect your integration for the service with ID {str(connection_id)} "
                            "and try again.",
                        ) from err
                    raise

                if response.status_code > 200:
                    raise errors.UnauthorizedError(message="Could not get installation information.")

                return adapter.api_validate_app_installations_response(response)

            return models.AppInstallationList(total_count=0, installations=[])

    @asynccontextmanager
    async def get_async_oauth2_client(
        self, connection_id: ULID, user: base_models.APIUser
    ) -> AsyncGenerator[tuple[AsyncOAuth2Client, schemas.OAuth2ConnectionORM, ProviderAdapter], None]:
        """Get the AsyncOAuth2Client for the given connection_id and user."""
        if not user.is_authenticated or user.id is None:
            raise errors.MissingResourceError(
                message=f"OAuth2 connection with id '{connection_id}' does not exist or you do not have access to it."
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

            if connection.status != models.ConnectionStatus.connected or connection.token is None:
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
