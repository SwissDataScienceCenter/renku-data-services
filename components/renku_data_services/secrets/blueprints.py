"""Secrets blueprint."""

import contextlib
from dataclasses import dataclass

from cryptography.hazmat.primitives.asymmetric import rsa
from kubernetes import client as k8s_client
from sanic import Request
from sanic_ext import validate
from sqlalchemy.util import b64encode

import renku_data_services.base_models as base_models
from renku_data_services.base_api.auth import authenticate, only_authenticated
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.k8s.client_interfaces import K8sCoreClientInterface
from renku_data_services.secrets import apispec
from renku_data_services.users.db import UserSecretsRepo
from renku_data_services.utils.cryptography import decrypt_rsa


@dataclass(kw_only=True)
class K8sSecretsBP(CustomBlueprint):
    """Handlers for using user secrets in K8s."""

    authenticator: base_models.Authenticator
    user_secrets_repo: UserSecretsRepo
    secret_service_private_key: rsa.RSAPrivateKey
    core_client: K8sCoreClientInterface

    def post(self) -> BlueprintFactoryResponse:
        """Create a new K8s secret from a user secret."""

        @authenticate(self.authenticator)
        @only_authenticated
        @validate(json=apispec.K8sSecret)
        async def _post(_: Request, *, requested_by: base_models.APIUser, body: apispec.K8sSecret):
            secrets = await self.user_secrets_repo.get_secrets_by_ids(
                requested_by=requested_by, secret_ids=[id.root for id in body.secret_ids]
            )
            decrypted_secrets = {
                s.name: b64encode(decrypt_rsa(self.secret_service_private_key, s.encrypted_value)) for s in secrets
            }

            with contextlib.suppress(k8s_client.ApiException):
                # try and delete the secret in case it already existed
                self.core_client.delete_namespaced_secret(body.name, body.namespace)

            secret = k8s_client.V1Secret(
                data=decrypted_secrets,
                metadata={"name": body.name, "namespace": body.namespace, "ownerReferences": body.owner_references},
            )

            self.core_client.create_namespaced_secret(body.namespace, secret)

        return "/k8s_secrets", ["POST"], _post
