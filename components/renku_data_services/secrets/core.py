"""Business logic for secrets storage."""

from __future__ import annotations

from base64 import b64encode

from box import Box
from cryptography.hazmat.primitives.asymmetric import rsa
from kr8s.objects import Secret
from kubernetes import client as k8s_client
from ulid import ULID

from renku_data_services import base_models, errors
from renku_data_services.k8s.constants import DEFAULT_K8S_CLUSTER, ClusterId
from renku_data_services.k8s.models import GVK, K8sSecret, sanitizer
from renku_data_services.secrets import apispec
from renku_data_services.secrets.db import LowLevelUserSecretsRepo
from renku_data_services.secrets.models import OwnerReference
from renku_data_services.utils.cryptography import (
    decrypt_rsa,
    decrypt_string,
)


async def validate_secret(
    user: base_models.APIUser,
    body: apispec.K8sSecret,
    secrets_repo: LowLevelUserSecretsRepo,
    secret_service_private_key: rsa.RSAPrivateKey,
    previous_secret_service_private_key: rsa.RSAPrivateKey | None,
) -> K8sSecret:
    """Creates a single k8s secret from a list of user secrets stored in the DB."""
    cluster_id = ClusterId(ULID.from_str(body.cluster_id)) if body.cluster_id is not None else DEFAULT_K8S_CLUSTER

    owner_references = []
    if body.owner_references:
        owner_references = [OwnerReference.from_dict(o) for o in body.owner_references]
    secret_ids = [ULID.from_str(id.root) for id in body.secret_ids]

    secrets = await secrets_repo.get_secrets_by_ids(requested_by=user, secret_ids=secret_ids)
    found_secret_ids = {str(s.id) for s in secrets}
    requested_secret_ids = set(map(str, secret_ids))
    missing_secret_ids = requested_secret_ids - found_secret_ids
    if len(missing_secret_ids) > 0:
        raise errors.MissingResourceError(message=f"Couldn't find secrets with ids {', '.join(missing_secret_ids)}")

    def _ensure_list(value: str | list[str]) -> list[str]:
        return [value] if isinstance(value, str) else value

    key_mapping_with_lists_only = (
        {key: _ensure_list(value) for key, value in body.key_mapping.items()} if body.key_mapping else None
    )

    if key_mapping_with_lists_only:
        if key_mapping_with_lists_only.keys() != requested_secret_ids:
            raise errors.ValidationError(message="Key mapping must include all requested secret IDs")

        all_keys = [key for value in key_mapping_with_lists_only.values() for key in value]
        if len(all_keys) != len(set(all_keys)):
            raise errors.ValidationError(message="Key mapping values are not unique")

    decrypted_secrets = {}
    try:
        for secret in secrets:
            try:
                decryption_key = decrypt_rsa(secret_service_private_key, secret.encrypted_key)
            except ValueError:
                if previous_secret_service_private_key is not None:
                    # If we're rotating keys right now, try the old key
                    decryption_key = decrypt_rsa(previous_secret_service_private_key, secret.encrypted_key)
                else:
                    raise

            decrypted_value = decrypt_string(decryption_key, user.id, secret.encrypted_value).encode()  # type: ignore

            keys = (
                key_mapping_with_lists_only[str(secret.id)]
                if key_mapping_with_lists_only
                else [secret.default_filename]
            )
            for key in keys:
                decrypted_secrets[key] = b64encode(decrypted_value).decode()
    except Exception as e:
        # don't wrap the error, we don't want secrets accidentally leaking.
        raise errors.SecretDecryptionError(message=f"An error occurred decrypting secrets: {str(type(e))}") from None

    owner_refs = []
    if owner_references:
        owner_refs = [o.to_k8s() for o in owner_references]

    v1_secret = k8s_client.V1Secret(
        data=decrypted_secrets,
        metadata=k8s_client.V1ObjectMeta(
            name=body.name,
            namespace=body.namespace,
            owner_references=owner_refs,
        ),
    )

    return K8sSecret(
        name=v1_secret.metadata.name,
        namespace=v1_secret.metadata.namespace,
        cluster=cluster_id,
        gvk=GVK(group="core", version=Secret.version, kind="Secret"),
        manifest=Box(sanitizer(v1_secret)),
    )
