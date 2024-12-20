"""Secrets blueprint."""

from dataclasses import dataclass

from cryptography.hazmat.primitives.asymmetric import rsa
from sanic import Request, json
from sanic.response import JSONResponse
from sanic_ext import validate
from ulid import ULID

import renku_data_services.base_models as base_models
from renku_data_services.base_api.auth import authenticate, only_authenticated
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.k8s.client_interfaces import K8sCoreClientInterface
from renku_data_services.secrets import apispec
from renku_data_services.secrets.core import create_k8s_secret
from renku_data_services.secrets.db import LowLevelUserSecretsRepo
from renku_data_services.secrets.models import OwnerReference


@dataclass(kw_only=True)
class K8sSecretsBP(CustomBlueprint):
    """Handlers for using user secrets in K8s."""

    authenticator: base_models.Authenticator
    user_secrets_repo: LowLevelUserSecretsRepo
    secret_service_private_key: rsa.RSAPrivateKey
    previous_secret_service_private_key: rsa.RSAPrivateKey | None
    core_client: K8sCoreClientInterface

    def post(self) -> BlueprintFactoryResponse:
        """Create a new K8s secret from a user secret."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate(json=apispec.K8sSecret)
        async def _post(_: Request, user: base_models.APIUser, body: apispec.K8sSecret) -> JSONResponse:
            owner_references = []
            if body.owner_references:
                owner_references = [OwnerReference.from_dict(o) for o in body.owner_references]
            secret_ids = [ULID.from_str(id.root) for id in body.secret_ids]
            await create_k8s_secret(
                user=user,
                secret_name=body.name,
                namespace=body.namespace,
                secret_ids=secret_ids,
                owner_references=owner_references,
                secrets_repo=self.user_secrets_repo,
                secret_service_private_key=self.secret_service_private_key,
                previous_secret_service_private_key=self.previous_secret_service_private_key,
                core_client=self.core_client,
                key_mapping=body.key_mapping,
            )

            return json(body.name, 201)

        return "/kubernetes", ["POST"], _post
