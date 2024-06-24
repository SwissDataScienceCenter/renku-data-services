"""Platform configuration blueprint."""

from dataclasses import dataclass

from sanic import Request
from sanic.response import JSONResponse

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.base_api.auth import authenticate, only_admins
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.base_api.etag import extract_if_none_match


@dataclass(kw_only=True)
class PlatformConfigBP(CustomBlueprint):
    """Handlers for the platform configuration."""

    authenticator: base_models.Authenticator

    def get_singleton(self) -> BlueprintFactoryResponse:
        """Get the platform configuration."""

        @extract_if_none_match
        async def _get_singleton(request: Request, user: base_models.APIUser, etag: str | None) -> JSONResponse:
            raise errors.MissingResourceError(message="The platform configuration has not been initialized yet")

        return "/platform/config", ["GET"], _get_singleton

    def post_singleton(self) -> BlueprintFactoryResponse:
        """Create the initial platform configuration."""

        @authenticate(self.authenticator)
        @only_admins
        async def _post_singleton(request: Request, user: base_models.APIUser) -> JSONResponse:
            raise errors.ProgrammingError(message="Not yet implemented")

        return "/platform/config", ["POST"], _post_singleton

    def patch_singleton(self) -> BlueprintFactoryResponse:
        """Update the platform configuration."""

        @authenticate(self.authenticator)
        @only_admins
        async def _patch_singleton(request: Request, user: base_models.APIUser) -> JSONResponse:
            raise errors.ProgrammingError(message="Not yet implemented")

        return "/platform/config", ["PATCH"], _patch_singleton
