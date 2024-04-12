"""Blueprints for the user endpoints."""

from dataclasses import dataclass

from cryptography.hazmat.primitives.asymmetric import rsa
from sanic import HTTPResponse, Request, json
from sanic_ext import validate

import renku_data_services.base_models as base_models
from renku_data_services.base_api.auth import authenticate, only_authenticated
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.errors import errors
from renku_data_services.users import apispec
from renku_data_services.users.db import UserRepo, UserSecretsRepo
from renku_data_services.users.models import Secret
from renku_data_services.utils.cryptography import encrypt_rsa, encrypt_string


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
    """Handlers for user secrets.

    Secrets storage is jointly handled by data service and secret service.
    Each user has their own secret key 'user_secret', encrypted at rest, that only data service can decrypt.
    Secret service has a public private key combo where only it knows the private key. To store a secret,
    it is first enrypted with the user_secret, and then with the secret service public key, and then stored
    in the database. This way neither the data service nor the secret service can decrypt the secrets on their
    own.
    """

    secret_repo: UserSecretsRepo
    user_repo: UserRepo
    authenticator: base_models.Authenticator
    secret_service_public_key: rsa.RSAPublicKey

    @only_authenticated
    async def _encrypt_user_secret(self, requested_by: base_models.APIUser, value: str) -> bytes:
        """Doubly encrypt a secret for a user."""
        secret_key = await self.user_repo.get_or_create_user_secret_key(requested_by=requested_by)
        # encrypt once with user secret
        encrypted_value = encrypt_string(secret_key.encode(), requested_by.id, value)  # type: ignore
        # encrypt again with secret service public key
        encrypted_value = encrypt_rsa(self.secret_service_public_key, encrypted_value)
        return encrypted_value

    def get_all(self) -> BlueprintFactoryResponse:
        """Get all user's secrets."""

        @authenticate(self.authenticator)
        @only_authenticated
        async def _get_all(request: Request, user: base_models.APIUser):
            secrets = await self.secret_repo.get_secrets(requested_by=user)
            return json(
                apispec.SecretsList(
                    root=[apispec.SecretWithId.model_validate(secret) for secret in secrets]
                ).model_dump(mode="json"),
                200,
            )

        return "/user/secrets", ["GET"], _get_all

    def get_one(self) -> BlueprintFactoryResponse:
        """Get a user secret."""

        @authenticate(self.authenticator)
        @only_authenticated
        async def _get_one(request: Request, secret_id: str, user: base_models.APIUser):
            secret = await self.secret_repo.get_secret_by_id(requested_by=user, secret_id=secret_id)
            if not secret:
                raise errors.MissingResourceError(message=f"The secret with id {secret_id} cannot be found.")

            return json(apispec.SecretWithId.model_validate(secret).model_dump(mode="json"))

        return "/user/secrets/<secret_id>", ["GET"], _get_one

    def post(self) -> BlueprintFactoryResponse:
        """Create a new secret."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate(json=apispec.SecretPost)
        async def _post(_: Request, *, user: base_models.APIUser, body: apispec.SecretPost):
            secret = Secret(
                name=body.name,
                encrypted_value=await self._encrypt_user_secret(requested_by=user, value=body.value),
            )
            result = await self.secret_repo.insert_secret(requested_by=user, secret=secret)
            return json(apispec.SecretWithId.model_validate(result).model_dump(exclude_none=True, mode="json"), 201)

        return "/user/secrets", ["POST"], _post

    def patch(self) -> BlueprintFactoryResponse:
        """Update a specific secret."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate(json=apispec.SecretPatch)
        async def _patch(_: Request, *, user: base_models.APIUser, secret_id: str, body: apispec.SecretPatch):
            encrypted_value = await self._encrypt_user_secret(requested_by=user, value=body.value)
            updated_secret = await self.secret_repo.update_secret(
                requested_by=user, secret_id=secret_id, encrypted_value=encrypted_value
            )

            return json(apispec.SecretWithId.model_validate(updated_secret).model_dump(exclude_none=True, mode="json"))

        return "/user/secrets/<secret_id>", ["PATCH"], _patch

    def delete(self) -> BlueprintFactoryResponse:
        """Delete a specific secret."""

        @authenticate(self.authenticator)
        @only_authenticated
        async def _delete(_: Request, *, user: base_models.APIUser, secret_id: str):
            await self.secret_repo.delete_secret(requested_by=user, secret_id=secret_id)
            return HTTPResponse(status=204)

        return "/user/secrets/<secret_id>", ["DELETE"], _delete
