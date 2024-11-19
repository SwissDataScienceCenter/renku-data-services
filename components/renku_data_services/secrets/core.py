"""Business logic for secrets storage."""

import asyncio
from base64 import b64encode

from cryptography.hazmat.primitives.asymmetric import rsa
from kubernetes import client as k8s_client
from prometheus_client import Counter, Enum
from sanic.log import logger
from ulid import ULID

from renku_data_services import base_models, errors
from renku_data_services.base_models.core import InternalServiceAdmin
from renku_data_services.k8s.client_interfaces import K8sCoreClientInterface
from renku_data_services.secrets.db import UserSecretsRepo
from renku_data_services.secrets.models import OwnerReference, Secret
from renku_data_services.users.db import UserRepo
from renku_data_services.utils.cryptography import (
    decrypt_rsa,
    decrypt_string,
    encrypt_rsa,
    encrypt_string,
    generate_random_encryption_key,
)


async def create_k8s_secret(
    user: base_models.APIUser,
    secret_name: str,
    namespace: str,
    secret_ids: list[ULID],
    owner_references: list[OwnerReference],
    secrets_repo: UserSecretsRepo,
    secret_service_private_key: rsa.RSAPrivateKey,
    previous_secret_service_private_key: rsa.RSAPrivateKey | None,
    core_client: K8sCoreClientInterface,
    key_mapping: dict[str, str | list[str]] | None,
) -> None:
    """Creates a single k8s secret from a list of user secrets stored in the DB."""
    secrets = await secrets_repo.get_secrets_by_ids(requested_by=user, secret_ids=secret_ids)
    found_secret_ids = {str(s.id) for s in secrets}
    requested_secret_ids = set(map(str, secret_ids))
    missing_secret_ids = requested_secret_ids - found_secret_ids
    if len(missing_secret_ids) > 0:
        raise errors.MissingResourceError(message=f"Couldn't find secrets with ids {', '.join(missing_secret_ids)}")

    if key_mapping and set(key_mapping) != requested_secret_ids:
        raise errors.ValidationError(message="Key mapping must include all requested secret IDs")

    # if key_mapping:
    #     if set(key_mapping) != requested_secret_ids:
    #         raise errors.ValidationError(message="Key mapping must include all requested secret IDs")
    # TODO: update the check below
    # if len(key_mapping) != len(set(key_mapping.values())):
    #     raise errors.ValidationError(message="Key mapping values are not unique")

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

            single_or_multi_key = key_mapping[str(secret.id)] if key_mapping else secret.name
            keys = [single_or_multi_key] if isinstance(single_or_multi_key, str) else single_or_multi_key
            for key in keys:
                decrypted_secrets[key] = b64encode(decrypted_value).decode()
    except Exception as e:
        # don't wrap the error, we don't want secrets accidentally leaking.
        raise errors.SecretDecryptionError(message=f"An error occurred decrypting secrets: {str(type(e))}")

    owner_refs = []
    if owner_references:
        owner_refs = [o.to_k8s() for o in owner_references]
    secret = k8s_client.V1Secret(
        data=decrypted_secrets,
        metadata=k8s_client.V1ObjectMeta(
            name=secret_name,
            namespace=namespace,
            owner_references=owner_refs,
        ),
    )

    try:
        core_client.create_namespaced_secret(namespace, secret)
    except k8s_client.ApiException as e:
        if e.status == 409:
            logger.info(
                f"Found that secret {namespace}/{secret_name} already exists when trying to create it, "
                "the existing secret will be patched"
            )
            sanitized_secret = k8s_client.ApiClient().sanitize_for_serialization(secret)
            core_client.patch_namespaced_secret(
                namespace,
                secret_name,
                sanitized_secret,
            )
        # don't wrap the error, we don't want secrets accidentally leaking.
        raise errors.SecretCreationError(message=f"An error occurred creating secrets: {str(type(e))}")


async def rotate_encryption_keys(
    requested_by: InternalServiceAdmin,
    new_key: rsa.RSAPrivateKey,
    old_key: rsa.RSAPrivateKey,
    secrets_repo: UserSecretsRepo,
    batch_size: int = 100,
) -> None:
    """Rotate all secrets to a new private key.

    This method undoes the outer encryption and reencrypts with a new key, without touching the inner encryption.
    """
    processed_secrets_metrics = Counter(
        "secrets_rotation_count",
        "Number of secrets rotated",
    )
    running_metrics = Enum(
        "secrets_rotation_state", "State of secrets rotation", states=["running", "finished", "errored"]
    )
    running_metrics.state("running")
    try:
        async for batch in secrets_repo.get_all_secrets_batched(requested_by, batch_size):
            updated_secrets = []
            for secret, user_id in batch:
                new_secret = await rotate_single_encryption_key(secret, user_id, new_key, old_key)
                # we need to sleep, otherwise the async scheduler will never yield to other tasks like requests
                await asyncio.sleep(0.000001)
                if new_secret is not None:
                    updated_secrets.append(new_secret)

            await secrets_repo.update_secrets(requested_by, updated_secrets)
            processed_secrets_metrics.inc(len(updated_secrets))
    except:
        running_metrics.state("errored")
        raise
    else:
        running_metrics.state("finished")


async def rotate_single_encryption_key(
    secret: Secret, user_id: str, new_key: rsa.RSAPrivateKey, old_key: rsa.RSAPrivateKey
) -> Secret | None:
    """Rotate a single secret in place."""
    # try using new key first as a sanity check, in case it was already rotated
    try:
        _ = decrypt_rsa(new_key, secret.encrypted_key)
    except ValueError:
        pass
    else:
        return None  # could decrypt with new key, nothing to do

    try:
        decryption_key = decrypt_rsa(old_key, secret.encrypted_key)
        decrypted_value = decrypt_string(decryption_key, user_id, secret.encrypted_value).encode()
        new_encryption_key = generate_random_encryption_key()
        secret.encrypted_value = encrypt_string(new_encryption_key, user_id, decrypted_value.decode())
        secret.encrypted_key = encrypt_rsa(new_key.public_key(), new_encryption_key)
    except Exception as e:
        logger.error(f"Couldn't decrypt secret {secret.name}({secret.id}): {e}")
        return None
    return secret


async def encrypt_user_secret(
    user_repo: UserRepo,
    requested_by: base_models.APIUser,
    secret_service_public_key: rsa.RSAPublicKey,
    secret_value: str,
) -> tuple[bytes, bytes]:
    """Doubly encrypt a secret for a user.

    Since RSA cannot encrypt arbitrary length strings, we use symmetric encryption with a random key and encrypt the
    random key with RSA to get it to the secret service.
    """
    if requested_by.id is None:
        raise errors.ValidationError(message="APIUser has no id")

    user_secret_key = await user_repo.get_or_create_user_secret_key(requested_by=requested_by)

    # encrypt once with user secret
    encrypted_value = encrypt_string(user_secret_key.encode(), requested_by.id, secret_value)
    # encrypt again with the secret service public key
    secret_svc_encryption_key = generate_random_encryption_key()
    doubly_encrypted_value = encrypt_string(secret_svc_encryption_key, requested_by.id, encrypted_value.decode())
    encrypted_key = encrypt_rsa(secret_service_public_key, secret_svc_encryption_key)
    return doubly_encrypted_value, encrypted_key
