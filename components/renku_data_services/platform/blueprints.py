"""Platform configuration blueprint."""

import urllib.parse
from dataclasses import dataclass
from typing import Any

from sanic import Request, empty
from sanic.response import HTTPResponse, JSONResponse
from sanic_ext import validate

import renku_data_services.base_models as base_models
from renku_data_services.base_api.auth import authenticate, only_admins
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.base_api.etag import extract_if_none_match, if_match_required
from renku_data_services.base_api.misc import validate_query
from renku_data_services.base_api.pagination import PaginationRequest, paginate
from renku_data_services.base_models.validation import validate_and_dump, validated_json
from renku_data_services.platform import apispec
from renku_data_services.platform.core import (
    validate_platform_config_patch,
    validate_url_redirect_patch,
    validate_url_redirect_post,
)
from renku_data_services.platform.db import PlatformRepository, UrlRedirectRepository
from renku_data_services.platform.models import UrlRedirectConfig


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
class PlatformUrlRedirectBP(CustomBlueprint):
    """Handlers for the platform redirects."""

    url_redirect_repo: UrlRedirectRepository
    authenticator: base_models.Authenticator

    @staticmethod
    def _dump_redirect(redirect: UrlRedirectConfig) -> dict[str, str]:
        """Dumps a project for API responses."""
        result = dict(
            etag=redirect.etag,
            source_url=redirect.source_url,
            target_url=redirect.target_url,
        )
        return result

    def delete_url_redirect_config(self) -> BlueprintFactoryResponse:
        """Delete a specific redirect config."""

        @authenticate(self.authenticator)
        @only_admins
        @if_match_required
        async def _delete_url_redirect_config(
            _: Request, user: base_models.APIUser, url: str, etag: str
        ) -> HTTPResponse:
            source_url = urllib.parse.unquote(url)
            await self.url_redirect_repo.delete_redirect_config(user=user, etag=etag, source_url=source_url)
            return HTTPResponse(status=204)

        return "/platform/redirects/<url>", ["DELETE"], _delete_url_redirect_config

    def get_url_redirect_configs(self) -> BlueprintFactoryResponse:
        """List all redirects."""

        @authenticate(self.authenticator)
        @only_admins
        @validate_query(query=apispec.PaginationRequest)
        @paginate
        async def _get_all_redirects(
            _: Request,
            user: base_models.APIUser,
            pagination: PaginationRequest,
            query: apispec.UrlRedirectPlansGetQuery,
        ) -> tuple[list[dict[str, Any]], int]:
            redirects, total_num = await self.url_redirect_repo.get_redirect_configs(user=user, pagination=pagination)

            redirects_list: list[dict[str, Any]] = [
                validate_and_dump(apispec.UrlRedirectPlan, self._dump_redirect(r)) for r in redirects
            ]
            return redirects_list, total_num

        return "/platform/redirects", ["GET"], _get_all_redirects

    def get_url_redirect_config(self) -> BlueprintFactoryResponse:
        """Get a specific redirect config."""

        @authenticate(self.authenticator)
        async def _get_url_redirect_config(_: Request, user: base_models.APIUser, url: str) -> JSONResponse:
            source_url = urllib.parse.unquote(url)
            redirect = await self.url_redirect_repo.get_redirect_config_by_source_url(user=user, source_url=source_url)
            return validated_json(apispec.UrlRedirectPlan, redirect)

        return "/platform/redirects/<url>", ["GET"], _get_url_redirect_config

    def post_url_redirect_config(self) -> BlueprintFactoryResponse:
        """Create a new redirect config."""

        @authenticate(self.authenticator)
        @only_admins
        @validate(json=apispec.UrlRedirectPlanPost)
        async def _post_redirect_config(
            _: Request,
            user: base_models.APIUser,
            body: apispec.UrlRedirectPlanPost,
        ) -> JSONResponse:
            url_redirect_post = validate_url_redirect_post(body)
            redirect = await self.url_redirect_repo.create_redirect_config(user=user, post=url_redirect_post)
            return validated_json(apispec.UrlRedirectPlan, redirect, status=201)

        return "/platform/redirects", ["POST"], _post_redirect_config

    def patch_url_redirect_config(self) -> BlueprintFactoryResponse:
        """Update a specific redirect config."""

        @authenticate(self.authenticator)
        @only_admins
        @if_match_required
        @validate(json=apispec.UrlRedirectPlanPatch)
        async def _patch_url_redirect_config(
            _: Request, user: base_models.APIUser, url: str, body: apispec.UrlRedirectPlanPatch, etag: str
        ) -> JSONResponse:
            source_url = urllib.parse.unquote(url)
            url_redirect_patch = validate_url_redirect_patch(source_url, body)

            updated_redirect = await self.url_redirect_repo.update_redirect_config(
                user=user, etag=etag, patch=url_redirect_patch
            )
            return validated_json(apispec.UrlRedirectPlan, updated_redirect)

        return "/platform/redirects/<url>", ["PATCH"], _patch_url_redirect_config
