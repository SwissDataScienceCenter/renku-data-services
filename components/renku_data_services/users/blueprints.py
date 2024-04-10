"""Blueprints for the user endpoints."""

from dataclasses import dataclass

from renku_data_services.users.models import Secret
from sanic import HTTPResponse, Request, json

import renku_data_services.base_models as base_models
from renku_data_services.base_api.auth import authenticate, only_authenticated
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.errors import errors
from renku_data_services.users.db import UserRepo, UserSecretRepo
from renku_data_services.users import apispec
from sanic_ext import validate


@dataclass(kw_only=True)
class KCUsersBP(CustomBlueprint):
    """Handlers for creating and listing users."""

    repo: UserRepo
    authenticator: base_models.Authenticator

    def get_all(self) -> BlueprintFactoryResponse:
        """Get all users or search by email."""

        @authenticate(self.authenticator)
        async def _get_all(request: Request, user: base_models.APIUser):
            email_filter = request.args.get("exact_email")
            users = await self.repo.get_users(requested_by=user, email=email_filter)
            return json(
                [
                    {"id": user.id, "first_name": user.first_name, "last_name": user.last_name, "email": user.email}
                    for user in users
                ]
            )

        return "/users", ["GET"], _get_all

    def get_self(self) -> BlueprintFactoryResponse:
        """Get info about the logged in user."""

        @authenticate(self.authenticator)
        async def _get_self(request: Request, user: base_models.APIUser):
            user_info = await self.repo.get_or_create_user(requested_by=user, id=user.id)
            if not user_info:
                raise errors.MissingResourceError(message=f"The user with ID {user.id} cannot be found.")
            return json(
                {
                    "id": user_info.id,
                    "first_name": user_info.first_name,
                    "last_name": user_info.last_name,
                    "email": user_info.email,
                }
            )

        return "/user", ["GET"], _get_self

    def get_one(self) -> BlueprintFactoryResponse:
        """Get info about a specific user."""

        @authenticate(self.authenticator)
        async def _get_one(request: Request, user_id: str, user: base_models.APIUser):
            user_info = await self.repo.get_or_create_user(requested_by=user, id=user_id)
            if not user_info:
                raise errors.MissingResourceError(message=f"The user with ID {user_id} cannot be found.")
            return json(
                {
                    "id": user_info.id,
                    "first_name": user_info.first_name,
                    "last_name": user_info.last_name,
                    "email": user_info.email,
                }
            )

        return "/users/<user_id>", ["GET"], _get_one


@dataclass(kw_only=True)
class UserSecretsBP(CustomBlueprint):
    """Handlers for user secrets."""

    secret_repo: UserSecretRepo
    user_repo: UserRepo
    authenticator: base_models.Authenticator

    def get_all(self) -> BlueprintFactoryResponse:
        """Get all user's secrets."""

        @authenticate(self.authenticator)
        @only_authenticated
        async def _get_all(request: Request, user_id: str, user: base_models.APIUser):
            secrets = await self.secret_repo.get_secrets(requested_by=user, user_id=user_id)
            return json(
                apispec.SecretsList(
                    root=[
                        apispec.SecretWithId(id=secret.id, name=secret.name, modification_date=secret.modification_date)
                        for secret in secrets
                    ]
                ).model_dump(mode="json"),
                200,
            )

        return "/users/<user_id>/secrets/", ["GET"], _get_all

    def get_one(self) -> BlueprintFactoryResponse:
        """Get a user secret."""

        @authenticate(self.authenticator)
        @only_authenticated
        async def _get_one(request: Request, user_id: str, secret_id: str, user: base_models.APIUser):
            secret = await self.secret_repo.get_secret_by_id(requested_by=user, user_id=user_id, secret_id=secret_id)
            if not secret:
                raise errors.MissingResourceError(message=f"The secret with id {secret_id} cannot be found.")

            return json(
                apispec.SecretWithId(
                    id=secret.id, name=secret.name, modification_date=secret.modification_date
                ).model_dump(mode="json")
            )

        return "/users/<user_id>/secrets/<secret_id>", ["GET"], _get_one

    def post(self) -> BlueprintFactoryResponse:
        """Create a new secret."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate(json=apispec.SecretPost)
        async def _post(_: Request, *, user: base_models.APIUser, user_id: str, body: apispec.SecretPost):
            target_user = await self.user_repo.get_user_secret_key(requested_by=user, id=user_id)
            result = await self.secret_repo.insert_secret(
                requested_by=user, user_id=user_id, secret=Secret.model_validate(body)
            )
            return json(apispec.SecretWithId.model_validate(result).model_dump(exclude_none=True, mode="json"), 201)

        return "/user/<user_id>/secrets", ["POST"], _post

    def patch(self) -> BlueprintFactoryResponse:
        """Update a specific secret."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate(json=apispec.SecretPatch)
        async def _patch(
            _: Request, *, user: base_models.APIUser, user_id: str, secret_id: str, body: apispec.SecretPatch
        ):
            updated_secret = await self.secret_repo.update_secret(
                requested_by=user, user_id=user_id, secret_id=secret_id, encrypted_value=body.value
            )

            return json(apispec.SecretWithId.model_validate(updated_secret).model_dump(exclude_none=True, mode="json"))

        return "/users/<user_id>/secrets/<secret_id>", ["PATCH"], _patch

    def delete(self) -> BlueprintFactoryResponse:
        """Delete a specific secret."""

        @authenticate(self.authenticator)
        @only_authenticated
        async def _delete(_: Request, *, user: base_models.APIUser, user_id: str, secret_id: str):
            await self.secret_repo.delete_secret(requested_by=user, user_id=user_id, secret_id=secret_id)
            return HTTPResponse(status=204)

        return "/secrets/<secret_id>", ["DELETE"], _delete
