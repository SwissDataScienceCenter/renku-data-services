"""Secrets blueprint."""

from dataclasses import dataclass
from datetime import UTC, datetime

from sanic import HTTPResponse, Request, json
from sanic_ext import validate

import renku_data_services.base_models as base_models
from renku_data_services.base_api.auth import authenticate, only_authenticated
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.secrets_storage.secret import apispec, models
from renku_data_services.secrets_storage.secret.db import SecretRepository


@dataclass(kw_only=True)
class SecretsBP(CustomBlueprint):
    """Handlers for manipulating secrets."""

    secret_repo: SecretRepository
    authenticator: base_models.Authenticator

    def post(self) -> BlueprintFactoryResponse:
        """Create a new secret."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate(json=apispec.SecretPost)
        async def _post(_: Request, *, user: base_models.APIUser, body: apispec.SecretPost):
            data = body.model_dump(exclude_none=True)
            # NOTE: Set ``modification_date`` to override possible value set by users
            data["modification_date"] = datetime.now(UTC).replace(microsecond=0)
            secret = models.Secret.from_dict(data)
            result = await self.secret_repo.insert_secret(user=user, secret=secret)
            return json(apispec.Secret.model_validate(result).model_dump(exclude_none=True, mode="json"), 201)

        return "/secrets", ["POST"], _post

    def get_one(self) -> BlueprintFactoryResponse:
        """Get a specific secret."""

        @authenticate(self.authenticator)
        @only_authenticated
        async def _get_one(_: Request, *, user: base_models.APIUser, secret_id: str):
            secret = await self.secret_repo.get_secret(user=user, secret_id=secret_id)
            return json(apispec.Secret.model_validate(secret).model_dump(exclude_none=True, mode="json"))

        return "/secrets/<secret_id>", ["GET"], _get_one

    def get_all(self) -> BlueprintFactoryResponse:
        """List all secrets."""

        @authenticate(self.authenticator)
        @only_authenticated
        async def _get_all(_: Request, *, user: base_models.APIUser):
            secrets = await self.secret_repo.get_secrets(user=user)
            return json([apispec.Secret.model_validate(p).model_dump(exclude_none=True, mode="json") for p in secrets])

        return "/secrets", ["GET"], _get_all

    def delete(self) -> BlueprintFactoryResponse:
        """Delete a specific secret."""

        @authenticate(self.authenticator)
        @only_authenticated
        async def _delete(_: Request, *, user: base_models.APIUser, secret_id: str):
            await self.secret_repo.delete_secret(user=user, secret_id=secret_id)
            return HTTPResponse(status=204)

        return "/secrets/<secret_id>", ["DELETE"], _delete

    def patch(self) -> BlueprintFactoryResponse:
        """Update a specific secret's value."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate(json=apispec.SecretPatch)
        async def _patch(_: Request, *, user: base_models.APIUser, secret_id: str, body: apispec.SecretPatch):
            body_dict = body.model_dump(exclude_none=True)

            updated_secret = await self.secret_repo.update_secret(user=user, secret_id=secret_id, **body_dict)

            return json(apispec.Secret.model_validate(updated_secret).model_dump(exclude_none=True, mode="json"), 200)

        return "/secrets/<secret_id>", ["PATCH"], _patch
