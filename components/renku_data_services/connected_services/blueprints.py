"""Connected services blueprint."""
from dataclasses import dataclass

from sanic import HTTPResponse, Request, json, redirect
from sanic.log import logger
from sanic_ext import validate

import renku_data_services.base_models as base_models
from renku_data_services.base_api.auth import authenticate, only_admins, only_authenticated
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.connected_services import apispec
from renku_data_services.connected_services.db import ConnectedServicesRepository


@dataclass(kw_only=True)
class OAuth2ClientsBP(CustomBlueprint):
    """Handlers for using OAuth2 Clients."""

    connected_services_repo: ConnectedServicesRepository
    authenticator: base_models.Authenticator

    def get_all(self) -> BlueprintFactoryResponse:
        """List all OAuth2 Clients."""

        @authenticate(self.authenticator)
        async def _get_all(_: Request, user: base_models.APIUser):
            clients = await self.connected_services_repo.get_oauth2_clients(user=user)
            return json(
                [apispec.Provider.model_validate(c).model_dump(exclude_none=True, mode='json') for c in clients]
            )

        return "/oauth2/providers", ["GET"], _get_all

    def get_one(self) -> BlueprintFactoryResponse:
        """Get a specific OAuth2 Client."""

        @authenticate(self.authenticator)
        async def _get_one(_: Request, provider_id: str, user: base_models.APIUser):
            client = await self.connected_services_repo.get_oauth2_client(provider_id=provider_id, user=user)
            return json(apispec.Provider.model_validate(client).model_dump(exclude_none=True, mode="json"))

        return "/oauth2/providers/<provider_id>", ["GET"], _get_one

    def authorize(self) -> BlueprintFactoryResponse:
        """Authorize an OAuth2 Client."""

        @authenticate(self.authenticator)
        @only_authenticated
        async def _authorize(_: Request, provider_id: str, user: base_models.APIUser):
            url, state, cookie = await self.connected_services_repo.authorize_client(provider_id=provider_id, user=user)
            logger.debug(f"Started oauth2: {url} {state} {cookie}")
            response = redirect(to=url)
            response.add_cookie("renku-oauth2", cookie,httponly=True)
            return response

        return "/oauth2/providers/<provider_id>/authorize", ["GET"], _authorize

    def authorize_callback(self) -> BlueprintFactoryResponse:
        """OAuth2 authorization callback."""

        async def _callback(request: Request):
            cookie = request.cookies.get("renku-oauth2")
            cookie = cookie if cookie else ""
            token = await self.connected_services_repo.authorize_callback(cookie=cookie, rawUrl=request.url)
            logger.debug(f"Token: {token}")
            return HTTPResponse(status=200)

        return "/oauth2/callback", ["GET"], _callback


@dataclass(kw_only=True)
class AdminOAuth2ClientsBP(CustomBlueprint):
    """Handlers for manipulating OAuth2 Clients as an admin user."""

    connected_services_repo: ConnectedServicesRepository
    authenticator: base_models.Authenticator

    def get_all(self) -> BlueprintFactoryResponse:
        """List all OAuth2 Clients."""

        @authenticate(self.authenticator)
        @only_admins
        async def _get_all(_: Request, user: base_models.APIUser):
            clients = await self.connected_services_repo.get_oauth2_clients(user=user)
            return json(
                [apispec.AdminProvider.model_validate(c).model_dump(exclude_none=True, mode='json') for c in clients]
            )

        return "/oauth2/admin/providers", ["GET"], _get_all

    def get_one(self) -> BlueprintFactoryResponse:
        """Get a specific OAuth2 Client."""

        @authenticate(self.authenticator)
        async def _get_one(_: Request, provider_id: str, user: base_models.APIUser):
            client = await self.connected_services_repo.get_oauth2_client(user=user, provider_id=provider_id)
            return json(apispec.AdminProvider.model_validate(client).model_dump(exclude_none=True, mode="json"))

        return "/oauth2/admin/providers/<provider_id>", ["GET"], _get_one

    def post(self) -> BlueprintFactoryResponse:
        """Create a new OAuth2 Client."""

        @authenticate(self.authenticator)
        @only_admins
        @validate(json=apispec.AdminProviderPost)
        async def _post(_: Request, body: apispec.AdminProviderPost, user: base_models.APIUser):
            client = await self.connected_services_repo.insert_oauth2_client(user=user, new_client=body)
            return json(apispec.AdminProvider.model_validate(client).model_dump(exclude_none=True, mode='json'), 201)

        return "/oauth2/admin/providers", ["POST"], _post

    def patch(self) -> BlueprintFactoryResponse:
        """Partially update a specific OAuth2 Client."""

        @authenticate(self.authenticator)
        @only_admins
        @validate(json=apispec.AdminProviderPatch)
        async def _patch(_: Request, provider_id: str, body: apispec.AdminProviderPatch, user: base_models.APIUser):
            body_dict = body.model_dump(exclude_none=True)
            client = await self.connected_services_repo.update_oauth2_client(
                user=user, provider_id=provider_id, **body_dict
            )
            return json(apispec.AdminProvider.model_validate(client).model_dump(exclude_none=True, mode="json"))

        return "/oauth2/admin/providers/<provider_id>", ["PATCH"], _patch

    def delete(self) -> BlueprintFactoryResponse:
        """Delete a specific OAuth2 Client."""

        @authenticate(self.authenticator)
        @only_admins
        async def _delete(_: Request, provider_id: str, user: base_models.APIUser):
            await self.connected_services_repo.delete_oauth2_client(user=user, provider_id=provider_id)
            return HTTPResponse(status=204)

        return "/oauth2/admin/providers/<provider_id>", ["DELETE"], _delete
