"""Connected services blueprint."""

from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote, urlparse, urlunparse

from sanic import HTTPResponse, Request, json, redirect
from sanic.response import JSONResponse
from sanic_ext import validate
from ulid import ULID

import renku_data_services.base_models as base_models
from renku_data_services.app_config import logging
from renku_data_services.base_api.auth import authenticate, only_admins, only_authenticated
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.base_api.misc import validate_query
from renku_data_services.base_api.pagination import PaginationRequest, paginate
from renku_data_services.base_models.validation import validate_and_dump, validated_json
from renku_data_services.connected_services import apispec
from renku_data_services.connected_services.apispec_base import AuthorizeParams, CallbackParams
from renku_data_services.connected_services.core import validate_oauth2_client_patch, validate_unsaved_oauth2_client
from renku_data_services.connected_services.db import ConnectedServicesRepository

logger = logging.getLogger(__name__)


@dataclass(kw_only=True)
class OAuth2ClientsBP(CustomBlueprint):
    """Handlers for using OAuth2 Clients."""

    connected_services_repo: ConnectedServicesRepository
    authenticator: base_models.Authenticator

    def get_all(self) -> BlueprintFactoryResponse:
        """List all OAuth2 Clients."""

        @authenticate(self.authenticator)
        async def _get_all(_: Request, user: base_models.APIUser) -> JSONResponse:
            clients = await self.connected_services_repo.get_oauth2_clients(user=user)
            return validated_json(apispec.ProviderList, clients)

        return "/oauth2/providers", ["GET"], _get_all

    def get_one(self) -> BlueprintFactoryResponse:
        """Get a specific OAuth2 Client."""

        @authenticate(self.authenticator)
        async def _get_one(_: Request, user: base_models.APIUser, provider_id: str) -> JSONResponse:
            provider_id = unquote(provider_id)
            client = await self.connected_services_repo.get_oauth2_client(provider_id=provider_id, user=user)
            return validated_json(apispec.Provider, client)

        return "/oauth2/providers/<provider_id>", ["GET"], _get_one

    def post(self) -> BlueprintFactoryResponse:
        """Create a new OAuth2 Client."""

        @authenticate(self.authenticator)
        @only_admins
        @validate(json=apispec.ProviderPost)
        async def _post(_: Request, user: base_models.APIUser, body: apispec.ProviderPost) -> JSONResponse:
            new_client = validate_unsaved_oauth2_client(body)
            client = await self.connected_services_repo.insert_oauth2_client(user=user, new_client=new_client)
            return validated_json(apispec.Provider, client, 201)

        return "/oauth2/providers", ["POST"], _post

    def patch(self) -> BlueprintFactoryResponse:
        """Partially update a specific OAuth2 Client."""

        @authenticate(self.authenticator)
        @only_admins
        @validate(json=apispec.ProviderPatch)
        async def _patch(
            _: Request, user: base_models.APIUser, provider_id: str, body: apispec.ProviderPatch
        ) -> JSONResponse:
            provider_id = unquote(provider_id)
            client_patch = validate_oauth2_client_patch(body)
            client = await self.connected_services_repo.update_oauth2_client(
                user=user, provider_id=provider_id, patch=client_patch
            )
            return validated_json(apispec.Provider, client)

        return "/oauth2/providers/<provider_id>", ["PATCH"], _patch

    def delete(self) -> BlueprintFactoryResponse:
        """Delete a specific OAuth2 Client."""

        @authenticate(self.authenticator)
        @only_admins
        async def _delete(_: Request, user: base_models.APIUser, provider_id: str) -> HTTPResponse:
            provider_id = unquote(provider_id)
            await self.connected_services_repo.delete_oauth2_client(user=user, provider_id=provider_id)
            return HTTPResponse(status=204)

        return "/oauth2/providers/<provider_id>", ["DELETE"], _delete

    def authorize(self) -> BlueprintFactoryResponse:
        """Authorize an OAuth2 Client."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate_query(query=apispec.AuthorizeParams)
        async def _authorize(
            request: Request, user: base_models.APIUser, provider_id: str, query: AuthorizeParams
        ) -> HTTPResponse:
            provider_id = unquote(provider_id)
            callback_url = self._get_callback_url(request)
            url = await self.connected_services_repo.authorize_client(
                provider_id=provider_id, user=user, callback_url=callback_url, next_url=query.next_url
            )
            return redirect(to=url)

        return "/oauth2/providers/<provider_id>/authorize", ["GET"], _authorize

    def authorize_callback(self) -> BlueprintFactoryResponse:
        """OAuth2 authorization callback."""

        async def _callback(request: Request) -> HTTPResponse:
            params = CallbackParams.model_validate(dict(request.query_args))

            callback_url = self._get_callback_url(request)

            next_url = await self.connected_services_repo.authorize_callback(
                state=params.state, raw_url=request.url, callback_url=callback_url
            )

            return redirect(to=next_url) if next_url else json({"status": "OK"})

        return "/oauth2/callback", ["GET"], _callback

    def _get_callback_url(self, request: Request) -> str:
        callback_url = request.url_for(f"{self.name}.{self.authorize_callback.__name__}")
        # TODO: configure the server to trust the reverse proxy so that the request scheme is always "https".
        # TODO: see also https://github.com/SwissDataScienceCenter/renku-data-services/pull/225
        https_callback_url = urlunparse(urlparse(callback_url)._replace(scheme="https"))
        if https_callback_url != callback_url:
            logger.warning("Forcing the callback URL to use https. Trusted proxies configuration may be incorrect.")
        return https_callback_url


@dataclass(kw_only=True)
class OAuth2ConnectionsBP(CustomBlueprint):
    """Handlers for using OAuth2 connections."""

    connected_services_repo: ConnectedServicesRepository
    authenticator: base_models.Authenticator

    def get_all(self) -> BlueprintFactoryResponse:
        """List all OAuth2 connections."""

        @authenticate(self.authenticator)
        async def _get_all(_: Request, user: base_models.APIUser) -> JSONResponse:
            connections = await self.connected_services_repo.get_oauth2_connections(user=user)
            return validated_json(apispec.ConnectionList, connections)

        return "/oauth2/connections", ["GET"], _get_all

    def get_one(self) -> BlueprintFactoryResponse:
        """Get a specific OAuth2 connection."""

        @authenticate(self.authenticator)
        async def _get_one(_: Request, user: base_models.APIUser, connection_id: ULID) -> JSONResponse:
            connection = await self.connected_services_repo.get_oauth2_connection(
                connection_id=connection_id, user=user
            )
            return validated_json(apispec.Connection, connection)

        return "/oauth2/connections/<connection_id:ulid>", ["GET"], _get_one

    def get_account(self) -> BlueprintFactoryResponse:
        """Get the account information for a specific OAuth2 connection."""

        @authenticate(self.authenticator)
        async def _get_account(_: Request, user: base_models.APIUser, connection_id: ULID) -> JSONResponse:
            account = await self.connected_services_repo.get_oauth2_connected_account(
                connection_id=connection_id, user=user
            )
            return validated_json(apispec.ConnectedAccount, account)

        return "/oauth2/connections/<connection_id:ulid>/account", ["GET"], _get_account

    def get_token(self) -> BlueprintFactoryResponse:
        """Get the access token for a specific OAuth2 connection."""

        @authenticate(self.authenticator)
        async def _get_token(_: Request, user: base_models.APIUser, connection_id: ULID) -> JSONResponse:
            token = await self.connected_services_repo.get_oauth2_connection_token(
                connection_id=connection_id, user=user
            )
            return json(token.dump_for_api())

        return "/oauth2/connections/<connection_id:ulid>/token", ["GET"], _get_token

    def get_installations(self) -> BlueprintFactoryResponse:
        """Get the installations for a specific OAuth2 connection."""

        @authenticate(self.authenticator)
        @validate_query(query=apispec.PaginationRequest)
        @paginate
        async def _get_installations(
            _: Request,
            user: base_models.APIUser,
            connection_id: ULID,
            pagination: PaginationRequest,
            query: apispec.PaginationRequest,
        ) -> tuple[list[dict[str, Any]], int]:
            installations_list = await self.connected_services_repo.get_oauth2_app_installations(
                connection_id=connection_id,
                user=user,
                pagination=pagination,
            )
            body = validate_and_dump(apispec.AppInstallationList, installations_list.installations)
            return body, installations_list.total_count

        return "/oauth2/connections/<connection_id:ulid>/installations", ["GET"], _get_installations
