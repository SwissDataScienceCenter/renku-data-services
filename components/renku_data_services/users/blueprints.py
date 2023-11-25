"""Blueprints for the user endpoints."""
from dataclasses import dataclass

from sanic import Request, json

import renku_data_services.base_models as base_models
from renku_data_services.base_api.auth import authenticate, only_admins
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.users.db import UserRepo
from renku_data_services.users import apispec
from renku_data_services.errors import errors


@dataclass(kw_only=True)
class UsersBP(CustomBlueprint):
    """Handlers for creating and listing users."""

    repo: UserRepo
    authenticator: base_models.Authenticator

    def get_all(self) -> BlueprintFactoryResponse:
        """Get all users."""

        @authenticate(self.authenticator)
        @only_admins
        async def _get_all(request: Request, body: apispec.UserWithId, user: base_models.APIUser):
            email_filter = request.query_args.get("exact_email")
            users = await self.repo.get_users(requested_by=user, email=email_filter)
            return json(
                [apispec.UserWithId.model_validate(user).model_dump(exclude_none=True) for user in users]
            )
        
        return "/users", ["GET"], _get_all
    
    def get_self(self) -> BlueprintFactoryResponse:
        """Get info about the logged in user."""

        @authenticate(self.authenticator)
        async def _get_self(request: Request, body: apispec.UserWithId, user: base_models.APIUser):
            user = await self.repo.get_user(requested_by=user, id=user.id)
            if not user:
                raise errors.MissingResourceError(message=f"The user with ID {user.id} cannot be found.")
            return json(apispec.UserWithId.model_validate(user).model_dump(exclude_none=True))

        return "/user", ["GET"], _get_self

    def get_one(self) -> BlueprintFactoryResponse:
        """Get info about a specific user."""

        @authenticate(self.authenticator)
        async def _get_one(request: Request, body: apispec.UserWithId, user_id: str, user: base_models.APIUser):
            user = await self.repo.get_user(requested_by=user, id=user_id)
            if not user:
                raise errors.MissingResourceError(message=f"The user with ID {user_id} cannot be found.")
            return json(apispec.UserWithId.model_validate(user).model_dump(exclude_none=True))

        return "/users/<user_id>", ["GET"], _get_one
