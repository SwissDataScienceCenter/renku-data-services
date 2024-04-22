"""Connected services blueprint."""
from dataclasses import dataclass

from sanic import Request, json
from sanic_ext import validate

import renku_data_services.base_models as base_models
from renku_data_services.base_api.auth import authenticate, only_admins
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.connected_services import apispec
from renku_data_services.connected_services.db import ConnectedServicesRepository


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

    def post(self) -> BlueprintFactoryResponse:
        """Create a new OAuth2 Client."""

        @authenticate(self.authenticator)
        @only_admins
        @validate(json=apispec.AdminProviderPost)
        async def _post(_: Request, body: apispec.AdminProviderPost, user: base_models.APIUser):
            client = await self.connected_services_repo.insert_oauth2_client(user=user, new_client=body)
            return json(apispec.AdminProvider.model_validate(client).model_dump(exclude_none=True, mode='json'), 201)

        return "/oauth2/admin/providers", ["POST"], _post
