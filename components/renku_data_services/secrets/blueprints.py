"""Secrets blueprint."""

from dataclasses import dataclass

import kr8s
from cryptography.hazmat.primitives.asymmetric import rsa
from sanic import Request, json
from sanic.response import JSONResponse
from sanic_ext import validate

from renku_data_services import base_models
from renku_data_services.base_api.auth import authenticate, only_authenticated
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.errors import errors
from renku_data_services.k8s.client_interfaces import SecretClient
from renku_data_services.secrets import apispec
from renku_data_services.secrets.core import validate_secret
from renku_data_services.secrets.db import LowLevelUserSecretsRepo


@dataclass(kw_only=True)
class K8sSecretsBP(CustomBlueprint):
    """Handlers for using user secrets in K8s."""

    authenticator: base_models.Authenticator
    user_secrets_repo: LowLevelUserSecretsRepo
    secret_service_private_key: rsa.RSAPrivateKey
    previous_secret_service_private_key: rsa.RSAPrivateKey | None
    client: SecretClient

    def post(self) -> BlueprintFactoryResponse:
        """Create a new K8s secret from a user secret."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate(json=apispec.K8sSecret)
        async def _post(_: Request, user: base_models.APIUser, body: apispec.K8sSecret) -> JSONResponse:
            secret = await validate_secret(
                user=user,
                body=body,
                secrets_repo=self.user_secrets_repo,
                secret_service_private_key=self.secret_service_private_key,
                previous_secret_service_private_key=self.previous_secret_service_private_key,
            )

            try:
                result = await self.client.create_secret(secret)
            except kr8s.ServerError as e:
                if not e.response:
                    raise
                if e.response.status_code == 409:
                    # NOTE: It means that the secret already exists, so we try to patch
                    patch_res = await self.client.patch_secret(secret, patch=secret.to_patch())
            except Exception as e:
                # don't wrap the error, we don't want secrets accidentally leaking.
                raise errors.SecretCreationError(
                    message=f"An error occurred creating secrets: {str(type(e))}"
                ) from None

            return json(result.name, 201)

        return "/kubernetes", ["POST"], _post
