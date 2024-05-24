"""Connected services blueprint."""

from dataclasses import dataclass
from urllib.parse import urlunparse

from sanic import HTTPResponse, Request, json, redirect
from sanic.log import logger
from sanic_ext import validate

import renku_data_services.base_models as base_models
from renku_data_services.base_api.auth import authenticate, only_admins, only_authenticated
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.connected_services import apispec
from renku_data_services.connected_services.apispec_base import AuthorizeParams
from renku_data_services.connected_services.db import ConnectedServicesRepository


@dataclass(kw_only=True)
class OAuth2ClientsBP(CustomBlueprint):
    """Handlers for using OAuth2 Clients."""

    connected_services_repo: ConnectedServicesRepository
    authenticator: base_models.Authenticator

    def get_all(self) -> BlueprintFactoryResponse:
        """List all OAuth2 Clients."""

        @authenticate(self.authenticator)
        async def _get_all(r: Request, user: base_models.APIUser):
            test_url = r.url_for(f"{self.name}.get_all")
            logger.info(f"test_url = {test_url}")

            clients = await self.connected_services_repo.get_oauth2_clients(user=user)
            return json(
                [apispec.Provider.model_validate(c).model_dump(exclude_none=True, mode="json") for c in clients]
            )

        return "/oauth2/providers", ["GET"], _get_all

    def get_one(self) -> BlueprintFactoryResponse:
        """Get a specific OAuth2 Client."""

        @authenticate(self.authenticator)
        async def _get_one(_: Request, provider_id: str, user: base_models.APIUser):
            client = await self.connected_services_repo.get_oauth2_client(provider_id=provider_id, user=user)
            return json(apispec.Provider.model_validate(client).model_dump(exclude_none=True, mode="json"))

        return "/oauth2/providers/<provider_id>", ["GET"], _get_one

    def post(self) -> BlueprintFactoryResponse:
        """Create a new OAuth2 Client."""

        @authenticate(self.authenticator)
        @only_admins
        @validate(json=apispec.ProviderPost)
        async def _post(_: Request, body: apispec.ProviderPost, user: base_models.APIUser):
            client = await self.connected_services_repo.insert_oauth2_client(user=user, new_client=body)
            return json(apispec.Provider.model_validate(client).model_dump(exclude_none=True, mode="json"), 201)

        return "/oauth2/providers", ["POST"], _post

    def patch(self) -> BlueprintFactoryResponse:
        """Partially update a specific OAuth2 Client."""

        @authenticate(self.authenticator)
        @only_admins
        @validate(json=apispec.ProviderPatch)
        async def _patch(_: Request, provider_id: str, body: apispec.ProviderPatch, user: base_models.APIUser):
            body_dict = body.model_dump(exclude_none=True)
            client = await self.connected_services_repo.update_oauth2_client(
                user=user, provider_id=provider_id, **body_dict
            )
            return json(apispec.Provider.model_validate(client).model_dump(exclude_none=True, mode="json"))

        return "/oauth2/providers/<provider_id>", ["PATCH"], _patch

    def delete(self) -> BlueprintFactoryResponse:
        """Delete a specific OAuth2 Client."""

        @authenticate(self.authenticator)
        @only_admins
        async def _delete(_: Request, provider_id: str, user: base_models.APIUser):
            await self.connected_services_repo.delete_oauth2_client(user=user, provider_id=provider_id)
            return HTTPResponse(status=204)

        return "/oauth2/providers/<provider_id>", ["DELETE"], _delete

    def authorize(self) -> BlueprintFactoryResponse:
        """Authorize an OAuth2 Client."""

        @authenticate(self.authenticator)
        @only_authenticated
        async def _authorize(request: Request, provider_id: str, user: base_models.APIUser):
            params = AuthorizeParams.model_validate(dict(request.query_args))
            callback_url = self._get_callback_url(request)
            url = await self.connected_services_repo.authorize_client(
                provider_id=provider_id, user=user, callback_url=callback_url, next_url=params.next_url
            )
            return redirect(to=url)

        return "/oauth2/providers/<provider_id>/authorize", ["GET"], _authorize

    def authorize_callback(self) -> BlueprintFactoryResponse:
        """OAuth2 authorization callback."""

        async def _callback(request: Request):
            params = AuthorizeParams.model_validate(dict(request.query_args))

            callback_url = self._get_callback_url(request)
            next_url = params.next_url

            await self.connected_services_repo.authorize_callback(
                state=params.state, raw_url=request.url, callback_url=callback_url, next_url=next_url
            )

            return redirect(to=next_url) if next_url else json({"status": "OK"})

        return "/oauth2/callback", ["GET"], _callback

    def _get_callback_url(self, request: Request) -> str:
        # test_url = request.url_for("renku_data_services.oauth2_clients.authorize_callback")
        # logger.info(f"test_url = {test_url}")
        test_url = request.url_for(f"{self.name}.authorize_callback")
        logger.info(f"test_url = {test_url}")

        callback_path = "/api/data/oauth2/callback"
        return urlunparse(("https", request.host, callback_path, None, None, None))


@dataclass(kw_only=True)
class OAuth2ConnectionsBP(CustomBlueprint):
    """Handlers for using OAuth2 connections."""

    connected_services_repo: ConnectedServicesRepository
    authenticator: base_models.Authenticator

    def get_all(self) -> BlueprintFactoryResponse:
        """List all OAuth2 connections."""

        @authenticate(self.authenticator)
        async def _get_all(_: Request, user: base_models.APIUser):
            connections = await self.connected_services_repo.get_oauth2_connections(user=user)
            return json(
                [apispec.Connection.model_validate(c).model_dump(exclude_none=True, mode="json") for c in connections]
            )

        return "/oauth2/connections", ["GET"], _get_all

    def get_one(self) -> BlueprintFactoryResponse:
        """Get a specific OAuth2 connection."""

        @authenticate(self.authenticator)
        async def _get_one(_: Request, connection_id: str, user: base_models.APIUser):
            connection = await self.connected_services_repo.get_oauth2_connection(
                connection_id=connection_id, user=user
            )
            return json(apispec.Connection.model_validate(connection).model_dump(exclude_none=True, mode="json"))

        return "/oauth2/connections/<connection_id>", ["GET"], _get_one

    def get_account(self) -> BlueprintFactoryResponse:
        """Get the account information for a specific OAuth2 connection."""

        @authenticate(self.authenticator)
        async def _get_account(_: Request, connection_id: str, user: base_models.APIUser):
            account = await self.connected_services_repo.get_oauth2_connected_account(
                connection_id=connection_id, user=user
            )
            return json(apispec.ConnectedAccount.model_validate(account).model_dump(exclude_none=True, mode="json"))

        return "/oauth2/connections/<connection_id>/account", ["GET"], _get_account

    def get_token(self) -> BlueprintFactoryResponse:
        """Get the access token for a specific OAuth2 connection."""

        @authenticate(self.authenticator)
        async def _get_token(_: Request, connection_id: str, user: base_models.APIUser):
            token = await self.connected_services_repo.get_oauth2_connection_token(
                connection_id=connection_id, user=user
            )
            return json(token.dump_for_api())

        return "/oauth2/connections/<connection_id>/token", ["GET"], _get_token
