"""Internal authentication blueprint."""

from dataclasses import dataclass

from sanic import Request
from sanic.response import JSONResponse

from renku_data_services import base_models
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.project import apispec


@dataclass(kw_only=True)
class InternalAuthenticationBP(CustomBlueprint):
    """Handlers for internal authentication."""

    # authenticator: base_models.Authenticator[base_models.APIUser]

    def post_token(self) -> BlueprintFactoryResponse:
        """Obtain a fresh internal token."""

        # @authenticate(self.authenticator)
        # @only_authenticated
        async def _post_token(_: Request, user: base_models.APIUser, body: apispec.ProjectPost) -> JSONResponse:
            raise NotImplementedError()

        return "/internal/authentication/token", ["POST"], _post_token
