"""Secrets blueprint."""

import contextlib
from dataclasses import dataclass

from cryptography.hazmat.primitives.asymmetric import rsa
from kubernetes import client as k8s_client
from sanic import Request, empty
from sanic_ext import validate
from sqlalchemy.util import b64encode

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.base_api.auth import authenticate, only_authenticated
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.k8s.client_interfaces import K8sCoreClientInterface
from renku_data_services.secrets import apispec
from renku_data_services.secrets.db import UserSecretsRepo
from renku_data_services.utils.cryptography import decrypt_rsa, decrypt_string


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
        async def _post(_: Request, *, user: base_models.APIUser, body: apispec.K8sSecret):
            secrets = await self.user_secrets_repo.get_secrets_by_ids(
                requested_by=user, secret_ids=[id.root for id in body.secret_ids]
            )
            found_secret_ids = {str(s.id) for s in secrets}
            requested_secret_ids = {s.root for s in body.secret_ids}
            missing_secret_ids = requested_secret_ids - found_secret_ids
            if len(missing_secret_ids) > 0:
                raise errors.MissingResourceError(
                    message=f"Couldn't find secrets with ids {', '.join(missing_secret_ids)}"
                )
            decrypted_secrets = {}
            for secret in secrets:
                decryption_key = decrypt_rsa(self.secret_service_private_key, secret.encrypted_key)
                decrypted_value = decrypt_string(decryption_key, user.id, secret.encrypted_value).encode()  # type: ignore
                decrypted_secrets[secret.name] = b64encode(decrypted_value)

            with contextlib.suppress(k8s_client.ApiException):
                # try and delete the secret in case it already existed
                self.core_client.delete_namespaced_secret(body.name, body.namespace)

            secret = k8s_client.V1Secret(
                data=decrypted_secrets,
                metadata={"name": body.name, "namespace": body.namespace, "owner_references": body.owner_references},
            )

            self.core_client.create_namespaced_secret(body.namespace, secret)
            return empty(201)

        return "/k8s_secret", ["POST"], _post
