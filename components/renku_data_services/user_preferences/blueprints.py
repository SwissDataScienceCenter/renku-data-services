"""User preferences app."""
from dataclasses import dataclass

from sanic import Request, json

import renku_data_services.base_models as base_models
from renku_data_services.base_api.auth import authenticate
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.user_preferences import apispec, models
from renku_data_services.user_preferences.db import UserPreferencesRepository


@dataclass(kw_only=True)
class UserPreferencesBP(CustomBlueprint):
    """Handlers for manipulating user preferences."""

    user_preferences_repo: UserPreferencesRepository
    authenticator: base_models.Authenticator

    def get(self) -> BlueprintFactoryResponse:
        """Get user preferences for the logged in user."""

        @authenticate(self.authenticator)
        async def _get(_: Request, user: base_models.APIUser):
            user_preferences: models.UserPreferences | None
            user_preferences = await self.user_preferences_repo.get_user_preferences(user=user)
            return json(apispec.UserPreferences.model_validate(user_preferences).model_dump())

        return "/user_preferences", ["GET"], _get
