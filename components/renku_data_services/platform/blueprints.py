"""Platform configuration blueprint."""

from dataclasses import dataclass

from sanic import Request, empty
from sanic.response import HTTPResponse, JSONResponse
from sanic_ext import validate

import renku_data_services.base_models as base_models
from renku_data_services.base_api.auth import authenticate, only_admins, only_authenticated
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.base_api.etag import extract_if_none_match, if_match_required
from renku_data_services.base_api.pagination import PaginationRequest, paginate
from renku_data_services.base_models.validation import validate_and_dump, validated_json
from renku_data_services.errors import errors
from renku_data_services.platform import apispec
from renku_data_services.platform.core import validate_platform_config_patch
from renku_data_services.platform.db import PlatformRepository, RedirectRepository


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


@dataclass(kw_only=True)
class PlatformRedirectBP(CustomBlueprint):
    """Handlers for the platform redirects."""

    redirect_repo: RedirectRepository
    authenticator: base_models.Authenticator

    def get_redirect_configs(self) -> BlueprintFactoryResponse:
        """List all redirects."""

        @authenticate(self.authenticator)
        @only_admins
        @paginate
        async def _get_all_redirects(
            _: Request,
            _user: base_models.APIUser,
            pagination: PaginationRequest,
        ) -> JSONResponse:
            redirects, total_num = await self.redirect_repo.get_redirect_configs(pagination=pagination)

            redirects_list = [validate_and_dump(apispec.RedirectInfo, self._dump_redirect(r)) for r in redirects]
            return validated_json(apispec.RedirectInfoList, redirects_list, total=total_num)

        return "/platform/redirects", ["GET"], _get_all_redirects

    def get_redirect_config(self) -> BlueprintFactoryResponse:
        """Get a specific redirect config."""

        @authenticate(self.authenticator)
        @only_authenticated
        async def _get_redirect_config(_: Request, user: base_models.APIUser, redirect_id: str) -> JSONResponse:
            redirect = await self.redirect_repo.get_redirect(user=user, redirect_id=redirect_id)
            if not redirect:
                raise errors.NotFoundError(message=f"Redirect with id '{redirect_id}' not found.")

            return validated_json(apispec.RedirectInfo, redirect)

        return "/platform/redirects/<url>", ["GET"], _get_redirect_config
