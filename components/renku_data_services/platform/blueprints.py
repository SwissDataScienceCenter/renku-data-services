"""Platform configuration blueprint."""

from dataclasses import dataclass

from sanic import Request, empty
from sanic.response import HTTPResponse, JSONResponse
from sanic_ext import validate

import renku_data_services.base_models as base_models
from renku_data_services.base_api.auth import authenticate, only_admins
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.base_api.etag import extract_if_none_match, if_match_required
from renku_data_services.base_models.validation import validated_json
from renku_data_services.platform import apispec
from renku_data_services.platform.core import validate_platform_config_patch
from renku_data_services.platform.db import PlatformRepository


@dataclass(kw_only=True)
class PlatformConfigBP(CustomBlueprint):
    """Handlers for the platform configuration."""

    platform_repo: PlatformRepository
    authenticator: base_models.Authenticator

    def get_singleton_configuration(self) -> BlueprintFactoryResponse:
        """Get the platform configuration."""

        @extract_if_none_match
        async def _get_singleton_configuration(_: Request, etag: str | None) -> HTTPResponse:
            config = await self.platform_repo.get_or_create_config()

            if config.etag == etag:
                return empty(status=304)

            headers = {"ETag": config.etag}
            return validated_json(
                apispec.PlatformConfig,
                dict(
                    etag=config.etag,
                    incident_banner=config.incident_banner,
                ),
                headers=headers,
            )

        return "/platform/config", ["GET"], _get_singleton_configuration

    def patch_singleton_configuration(self) -> BlueprintFactoryResponse:
        """Update the platform configuration."""

        @authenticate(self.authenticator)
        @only_admins
        @if_match_required
        @validate(json=apispec.PlatformConfigPatch)
        async def _patch_singleton_configuration(
            _: Request, user: base_models.APIUser, body: apispec.PlatformConfigPatch, etag: str
        ) -> JSONResponse:
            platform_config_patch = validate_platform_config_patch(body)
            config = await self.platform_repo.update_config(user=user, etag=etag, patch=platform_config_patch)
            headers = {"ETag": config.etag}
            return validated_json(
                apispec.PlatformConfig,
                dict(
                    etag=config.etag,
                    incident_banner=config.incident_banner,
                ),
                headers=headers,
            )

        return "/platform/config", ["PATCH"], _patch_singleton_configuration
