"""Connected services blueprint."""

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import unquote, urlparse, urlunparse

import httpx
from sanic import HTTPResponse, Request, empty, json, redirect
from sanic.response import JSONResponse
from sanic_ext import validate
from ulid import ULID

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.app_config import logging
from renku_data_services.base_api.auth import authenticate, only_admins, only_authenticated
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.base_api.misc import validate_query
from renku_data_services.base_api.pagination import PaginationRequest, paginate
from renku_data_services.base_models.validation import validate_and_dump, validated_json
from renku_data_services.connected_services import apispec, apispec_extras
from renku_data_services.connected_services.apispec_base import AuthorizeParams, CallbackParams
from renku_data_services.connected_services.core import validate_oauth2_client_patch, validate_unsaved_oauth2_client
from renku_data_services.connected_services.db import ConnectedServicesRepository
from renku_data_services.connected_services.oauth_http import (
    OAuthHttpClientFactory,
    OAuthHttpError,
    OAuthHttpFactoryError,
)
from renku_data_services.notebooks.config import NotebooksConfig

logger = logging.getLogger(__name__)


@dataclass(kw_only=True)
class OAuth2ClientsBP(CustomBlueprint):
    """Handlers for using OAuth2 Clients."""

    connected_services_repo: ConnectedServicesRepository
    oauth_http_client_factory: OAuthHttpClientFactory
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
            url = await self.oauth_http_client_factory.initiate_oauth_flow(
                user=user, provider_id=provider_id, callback_url=callback_url, next_url=query.next_url
            )
            return redirect(to=url)

        return "/oauth2/providers/<provider_id>/authorize", ["GET"], _authorize

    def authorize_callback(self) -> BlueprintFactoryResponse:
        """OAuth2 authorization callback."""

        async def _callback(request: Request) -> HTTPResponse:
            params = CallbackParams.model_validate(dict(request.query_args))

            callback_url = self._get_callback_url(request)

            client = await self.oauth_http_client_factory.fetch_token(
                state=params.state, raw_url=request.url, callback_url=callback_url
            )
            match client:
                case OAuthHttpFactoryError() as err:
                    logger.info(f"Error obtaining token to finish authorizing: {err}")
                    # TODO: redirect to a error page (that needs to be created)
                    raise errors.ForbiddenError(message="You do not have the required permissions for this operation.")
                case _:
                    next_url = client.connection.next_url
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
    oauth_client_factory: OAuthHttpClientFactory
    authenticator: base_models.Authenticator
    nb_config: NotebooksConfig

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

    def delete(self) -> BlueprintFactoryResponse:
        """Delete a specific OAuth2 connection."""

        @authenticate(self.authenticator)
        async def _delete_one(_: Request, user: base_models.APIUser, connection_id: ULID) -> HTTPResponse:
            result = await self.connected_services_repo.delete_oauth2_connection(user, connection_id)

            return empty(status=204 if result else 404)

        return "/oauth2/connections/<connection_id:ulid>", ["DELETE"], _delete_one

    def get_account(self) -> BlueprintFactoryResponse:
        """Get the account information for a specific OAuth2 connection."""

        @authenticate(self.authenticator)
        async def _get_account(_: Request, user: base_models.APIUser, connection_id: ULID) -> JSONResponse:
            client = await self.oauth_client_factory.for_user_connection_raise(user, connection_id)
            account = await client.get_connected_account()
            match account:
                case OAuthHttpError() as err:
                    raise errors.InvalidTokenError(message=f"OAuth error getting the connected account: {err}")
                case account:
                    return validated_json(apispec.ConnectedAccount, account)

        return "/oauth2/connections/<connection_id:ulid>/account", ["GET"], _get_account

    def get_token(self) -> BlueprintFactoryResponse:
        """Get the access token for a specific OAuth2 connection."""

        @authenticate(self.authenticator)
        async def _get_token(_: Request, user: base_models.APIUser, connection_id: ULID) -> JSONResponse:
            client = await self.oauth_client_factory.for_user_connection_raise(user, connection_id)
            token = await client.get_token()
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
            client = await self.oauth_client_factory.for_user_connection_raise(user, connection_id)
            installations_list = await client.get_oauth2_app_installations(pagination)
            match installations_list:
                case OAuthHttpError() as err:
                    logger.info(f"Error getting app installations for user={user.id} conn={connection_id}: {err}")
                    raise errors.ForbiddenError(
                        message="You don't have the required permissions to perform this operation"
                    )
                case _:
                    body = validate_and_dump(apispec.AppInstallationList, installations_list.installations)
                    return body, installations_list.total_count

        return "/oauth2/connections/<connection_id:ulid>/installations", ["GET"], _get_installations

    def post_token_endpoint(self) -> BlueprintFactoryResponse:
        """OAuth 2.0 token endpoint to support applications running in sessions."""

        @validate(form=apispec_extras.PostTokenRequest)
        async def _post_token_endpoint(
            request: Request, body: apispec_extras.PostTokenRequest, connection_id: ULID
        ) -> JSONResponse:
            logger.warning(f"post_token_endpoint: connection_id = {str(connection_id)}")
            logger.warning(f"post_token_endpoint: request headers = {list(request.headers.keys())}")
            logger.warning(f"post_token_endpoint: request content-type = {request.headers.get("content-type")}")
            logger.warning(f"post_token_endpoint: request body = {request.body!r}")

            logger.warning(f"post_token_endpoint: request body grant_type = {body.grant_type.value}")
            logger.warning(f"post_token_endpoint: request body refresh_token = {body.refresh_token}")

            renku_tokens = apispec_extras.RenkuTokens.decode(body.refresh_token)
            logger.warning(f"post_token_endpoint: renku_tokens = {renku_tokens}")
            request.headers[self.authenticator.token_field] = renku_tokens.access_token

            user: base_models.APIUser | None = None
            try:
                _user = cast(
                    base_models.APIUser,
                    await self.authenticator.authenticate(
                        access_token=renku_tokens.access_token or "", request=request
                    ),
                )
                if _user.is_authenticated and _user.access_token:
                    user = _user
            except Exception as err:
                logger.error(f"Got authenticate error: {err.__class__}.")
                raise

            logger.warning(f"post_token_endpoint: user = {user}")

            # Try to refresh the Renku access token
            if user is None and renku_tokens.refresh_token:
                renku_base_url = "https://" + self.nb_config.sessions.ingress.host
                renku_base_url = renku_base_url.rstrip("/")
                renku_realm = self.nb_config.keycloak_realm
                renku_auth_token_uri = f"{renku_base_url}/auth/realms/{renku_realm}/protocol/openid-connect/token"

                async with httpx.AsyncClient(timeout=10) as http:
                    auth = (
                        self.nb_config.sessions.git_proxy.renku_client_id,
                        self.nb_config.sessions.git_proxy.renku_client_secret,
                    )
                    payload = {
                        "grant_type": "refresh_token",
                        "refresh_token": renku_tokens.refresh_token,
                    }
                    response = await http.post(renku_auth_token_uri, auth=auth, data=payload)
                    logger.warning(f"Get refresh response from Keycloak: {response}")
                    logger.warning(f"Get refresh response from Keycloak: {response.json()}")
                    pass

            if user is not None and user.is_authenticated:
                client = await self.oauth_client_factory.for_user_connection_raise(user, connection_id)
                oauth_token = await client.get_token()
                access_token = oauth_token.access_token
                if access_token is None:
                    raise errors.ProgrammingError(message="Unexpected error: access token not present.")
                result: dict[str, str | int] = {
                    "access_token": access_token,
                    "token_type": str(oauth_token.get("token_type")) or "Bearer",
                    "refresh_token": renku_tokens.encode(),
                }
                if oauth_token.get("scope"):
                    result["scope"] = oauth_token["scope"]
                if oauth_token.expires_at:
                    exp = datetime.fromtimestamp(oauth_token.expires_at, UTC)
                    expires_in = exp - datetime.now(UTC)
                    result["expires_in"] = math.ceil(expires_in.total_seconds())
                return validated_json(apispec_extras.PostTokenResponse, result)

            # TODO:
            # 1. Decode the refresh_token value -> RenkuTokens
            # 2. Validate the access_token -> if valid, send back the new OAuth 2.0 access token
            #    and the new encoded refresh_token
            # 3. If access_token is expired, use the renku refresh_token -> if new tokens are valid,
            #    send back the new OAuth 2.0 access token and the new encoded refresh_token

            raise NotImplementedError("TODO: post_token_endpoint()")

        return "/oauth2/connections/<connection_id:ulid>/token_endpoint", ["POST"], _post_token_endpoint
