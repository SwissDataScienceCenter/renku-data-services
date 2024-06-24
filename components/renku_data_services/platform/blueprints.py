"""Platform configuration blueprint."""

from dataclasses import dataclass

from sanic import Request, empty, json
from sanic.response import HTTPResponse, JSONResponse
from sanic_ext import validate

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.base_api.auth import authenticate, only_admins
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.base_api.etag import extract_if_none_match
from renku_data_services.platform import apispec
from renku_data_services.platform.db import PlatformRepository


@dataclass(kw_only=True)
class PlatformConfigBP(CustomBlueprint):
    """Handlers for the platform configuration."""

    platform_repo: PlatformRepository
    authenticator: base_models.Authenticator

    def get_singleton(self) -> BlueprintFactoryResponse:
        """Get the platform configuration."""

        @extract_if_none_match
        async def _get_singleton(_: Request, etag: str | None) -> HTTPResponse:
            config = await self.platform_repo.get_config()

            if config.etag == etag:
                return empty(status=304)

            headers = {"ETag": config.etag}
            return json(
                apispec.PlatformConfig.model_validate(
                    dict(
                        etag=config.etag,
                        disable_ui=config.disable_ui,
                        maintenance_banner=config.maintenance_banner,
                        status_page_id=config.status_page_id,
                    )
                ).model_dump(mode="json", exclude_none=True),
                headers=headers,
            )

        return "/platform/config", ["GET"], _get_singleton

    def post_singleton(self) -> BlueprintFactoryResponse:
        """Create the initial platform configuration."""

        @authenticate(self.authenticator)
        @only_admins
        @validate(json=apispec.PlatformConfigPost)
        async def _post_singleton(
            _: Request, user: base_models.APIUser, body: apispec.PlatformConfigPost
        ) -> JSONResponse:
            config = await self.platform_repo.insert_config(user=user, new_config=body)
            headers = {"ETag": config.etag}
            return json(
                apispec.PlatformConfig.model_validate(
                    dict(
                        etag=config.etag,
                        disable_ui=config.disable_ui,
                        maintenance_banner=config.maintenance_banner,
                        status_page_id=config.status_page_id,
                    )
                ).model_dump(mode="json", exclude_none=True),
                headers=headers,
                status=201,
            )

        return "/platform/config", ["POST"], _post_singleton

    def patch_singleton(self) -> BlueprintFactoryResponse:
        """Update the platform configuration."""

        @authenticate(self.authenticator)
        @only_admins
        async def _patch_singleton(request: Request, user: base_models.APIUser) -> JSONResponse:
            raise errors.ProgrammingError(message="Not yet implemented")

        return "/platform/config", ["PATCH"], _patch_singleton
