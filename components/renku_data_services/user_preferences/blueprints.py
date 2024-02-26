"""User preferences app."""

from dataclasses import dataclass

from sanic import HTTPResponse, Request, json
from sanic_ext import validate

import renku_data_services.base_models as base_models
from renku_data_services.base_api.auth import authenticate
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.user_preferences import apispec
from renku_data_services.user_preferences.apispec_base import PinnedProjectFilter
from renku_data_services.user_preferences.db import UserPreferencesRepository


@dataclass(kw_only=True)
class UserPreferencesBP(CustomBlueprint):
    """Handlers for manipulating user preferences."""

    user_preferences_repo: UserPreferencesRepository
    authenticator: base_models.Authenticator

    def get(self) -> BlueprintFactoryResponse:
        """Get user preferences for the logged in user."""

        @authenticate(self.authenticator)
        async def _get(request: Request, user: base_models.APIUser):
            user_preferences = await self.user_preferences_repo.get_user_preferences(user=user)

            etag = request.headers.get("If-None-Match")
            if user_preferences.etag is not None and user_preferences.etag == etag:
                return HTTPResponse(status=304)

            headers = {"ETag": user_preferences.etag} if user_preferences.etag is not None else None
            return json(
                apispec.UserPreferences.model_validate(user_preferences).model_dump(),
                headers=headers,
            )

        return "/user/preferences", ["GET"], _get

    def patch(self) -> BlueprintFactoryResponse:
        """Partially update the user preferences for the logged in user."""

        @authenticate(self.authenticator)
        @validate(json=apispec.UserPreferencesPatch)
        async def _patch(request: Request, body: apispec.UserPreferencesPatch, user: base_models.APIUser):
            etag = request.headers.get("If-Match")
            body_dict = body.model_dump(exclude_none=True)
            user_preferences = await self.user_preferences_repo.update_user_preferences(
                user=user, etag=etag, **body_dict
            )

            return json(apispec.UserPreferences.model_validate(user_preferences).model_dump())

        return "/user/preferences", ["PATCH"], _patch

    def post_pinned_projects(self) -> BlueprintFactoryResponse:
        """Add a pinned project to user preferences for the logged in user."""

        @authenticate(self.authenticator)
        @validate(json=apispec.AddPinnedProject)
        async def _post(_: Request, body: apispec.AddPinnedProject, user: base_models.APIUser):
            res = await self.user_preferences_repo.add_pinned_project(user=user, project_slug=body.project_slug)
            return json(apispec.UserPreferences.model_validate(res).model_dump())

        return "/user/preferences/pinned_projects", ["POST"], _post

    def delete_pinned_projects(self) -> BlueprintFactoryResponse:
        """Remove a pinned project from user preferences for the logged in user."""

        @authenticate(self.authenticator)
        async def _delete(request: Request, user: base_models.APIUser):
            res_filter = PinnedProjectFilter.model_validate(dict(request.query_args))
            res = await self.user_preferences_repo.remove_pinned_project(user=user, **res_filter.model_dump())
            return json(apispec.UserPreferences.model_validate(res).model_dump())

        return "/user/preferences/pinned_projects", ["DELETE"], _delete
