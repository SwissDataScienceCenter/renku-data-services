"""Business logic for secrets storage."""

from __future__ import annotations

from base64 import b64encode
from configparser import ConfigParser
from copy import deepcopy
from io import StringIO
from typing import Any

import kr8s
from box import Box
from cryptography.hazmat.primitives.asymmetric import rsa
from kubernetes import client as k8s_client
from ulid import ULID

from renku_data_services import base_models, errors
from renku_data_services.app_config import logging
from renku_data_services.k8s.client_interfaces import SecretClient
from renku_data_services.k8s.constants import DEFAULT_K8S_CLUSTER, ClusterId
from renku_data_services.k8s.models import K8sSecret, sanitizer
from renku_data_services.secrets import apispec
from renku_data_services.secrets.db import LowLevelUserSecretsRepo
from renku_data_services.secrets.models import OwnerReference, Secret
from renku_data_services.utils.cryptography import (
    decrypt_rsa,
    decrypt_string,
)

logger = logging.getLogger(__name__)


async def validate_secret(
    user: base_models.APIUser,
    body: apispec.K8sSecret,
    secrets_repo: LowLevelUserSecretsRepo,
    secret_service_private_key: rsa.RSAPrivateKey,
    previous_secret_service_private_key: rsa.RSAPrivateKey | None,
) -> K8sSecret:
    """Creates a single k8s secret from a list of user secrets stored in the DB."""
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
            keys = (
                key_mapping_with_lists_only[str(secret.id)]
                if key_mapping_with_lists_only
                else [secret.default_filename]
            )
            for key in keys:
                decrypted_secrets[key] = __decrypt_secret(
                    user, secret, secret_service_private_key, previous_secret_service_private_key
                )
    except Exception as e:
        # don't wrap the error, we don't want secrets accidentally leaking.
        raise errors.SecretDecryptionError(message=f"An error occurred decrypting secrets: {str(type(e))}") from None

    return __create_secret_manifest(
        body.name, body.namespace, body.cluster_id, body.owner_references, decrypted_secrets
    )


async def create_or_patch_secret(client: SecretClient, secret: K8sSecret) -> K8sSecret:
    """Create or patch a secret if it already exists."""
    logger.info(f"Creating secret {secret.namespace}/{secret.name}")
    try:
        result = await client.create_secret(secret)
    except kr8s.ServerError as e:
        if e.response and e.response.status_code == 409:
            # NOTE: It means that the secret already exists, so we try to patch
            msg = f"The secret {secret.namespace}/{secret.name} already exists, will try to patch it."
            # TODO: Add sentry integration to the secret service
            # sentry_sdk.capture_message(msg, level="warning")
            logger.warning(msg)
            result = await client.patch_secret(secret, patch=secret.to_patch())
            return result
        import logging

        logging.error(e)
        raise errors.SecretCreationError(message=f"An error occurred creating secrets: {str(type(e))}") from None
    except Exception as e:
        # don't wrap the error, we don't want secrets accidentally leaking.
        raise errors.SecretCreationError(message=f"An error occurred creating secrets: {str(type(e))}") from None
    return result


async def create_dc_config_secret(
    user: base_models.APIUser,
    body: apispec.DataConnectorsK8sSecret,
    secrets_repo: LowLevelUserSecretsRepo,
    secret_service_private_key: rsa.RSAPrivateKey,
    previous_secret_service_private_key: rsa.RSAPrivateKey | None = None,
) -> K8sSecret:
    """Create a k8s secret that contains the configuration for a set of data connectors."""
    import logging

    logging.warning(body)

    config = await __combine_dc_configs(
        user,
        body.data_connectors,
        secrets_repo,
        body.combined_remote_name,
        secret_service_private_key,
        previous_secret_service_private_key,
        user_key=body.user_private_key,
    )
    ini_config = __create_ini_style_config(config)
    return __create_secret_manifest(
        body.name, body.namespace, body.cluster_id, body.owner_references, {"config": ini_config}
    )


def __decrypt_secret(
    user: base_models.APIUser,
    secret: Secret,
    secret_service_private_key: rsa.RSAPrivateKey,
    previous_secret_service_private_key: rsa.RSAPrivateKey | None = None,
    user_key: str | None = None,
) -> str:
    import logging

    if not user.id:
        raise errors.UnauthorizedError(message="Cannot manage saved secrets for an unauthenticated user.")
    try:
        try:
            decryption_key = decrypt_rsa(secret_service_private_key, secret.encrypted_key)
        except ValueError:
            if previous_secret_service_private_key is not None:
                # If we're rotating keys right now, try the old key
                decryption_key = decrypt_rsa(previous_secret_service_private_key, secret.encrypted_key)
            else:
                raise

        decrypted_value = decrypt_string(decryption_key, user.id, secret.encrypted_value)
        if user_key:
            pass
            logging.warning(user_key, user.id, decrypted_value)
            # decrypted_value = decrypt_string(user_key.encode(), user.id, decrypted_value.encode())

    except Exception as e:
        # don't wrap the error, we don't want secrets accidentally leaking.
        raise errors.SecretDecryptionError(message=f"An error occurred decrypting secrets: {str(type(e))}") from None

    return decrypted_value


async def __combine_dc_configs(
    user: base_models.APIUser,
    dcs: list[apispec.DataConnectorWithSecrets],
    secrets_repo: LowLevelUserSecretsRepo,
    combined_remote_name: str,
    secret_service_private_key: rsa.RSAPrivateKey,
    previous_secret_service_private_key: rsa.RSAPrivateKey | None = None,
    user_key: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Combine the data connector secret and configurations."""
    output: dict[str, dict[str, Any]] = {}
    combined_conf: dict[str, Any] = {"type": "combine"}
    upstreams: list[str] = []
    for dc in dcs:
        dc_config = deepcopy(dc.config)

        if dc.secrets:
            if not user_key:
                raise errors.ProgrammingError(
                    message="The data connectos have secrets but the user key was not provided for decryption."
                )
            for secret_id in dc.secrets:
                secret_fields = dc.secrets[secret_id]
                secrets = await secrets_repo.get_secrets_by_ids(user, [ULID.from_str(secret_id)])
                if len(secrets) != 1:
                    raise errors.ProgrammingError(message=f"Expected to get one secret but did got {len(secrets)}")
                secret_enc = secrets[0]
                secret_dec = __decrypt_secret(
                    user, secret_enc, secret_service_private_key, previous_secret_service_private_key, user_key
                )
                if isinstance(secret_fields, str):
                    secret_fields = [secret_fields]
                for k in secret_fields:
                    dc_config[k] = secret_dec

        output[dc.remote_name] = dc_config
        upstreams.append(f"{dc.remote_name}={dc.remote_name}:{dc.remote_path or ''}")

    combined_conf["upstreams"] = " ".join(upstreams)
    output[combined_remote_name] = combined_conf
    return output


def __create_secret_manifest(
    name: str,
    namespace: str,
    cluster_id: ClusterId | str | ULID | None,
    owner_references: list[dict[str, str]],
    payload: dict[str, str],
    base64_encode: bool = True,
) -> K8sSecret:
    match cluster_id:
        case ULID():
            cluster_id = ClusterId(cluster_id)
        case str():
            cluster_id = ClusterId(ULID.from_str(cluster_id))
        case ClusterId():
            pass
        case None:
            cluster_id = None
        case _:
            raise errors.ValidationError(
                message=f"Cannot create secret manifest when the cluster id is of unexpected type: {type(cluster_id)}"
            )

    owner_refs = []
    if owner_references:
        owner_refs = [OwnerReference.from_dict(o).to_k8s() for o in owner_references]

    import logging

    logging.warning(payload)
    if base64_encode:
        for k in payload:
            payload[k] = b64encode(payload[k].encode()).decode()

    logging.warning(payload)
    v1_secret = k8s_client.V1Secret(
        data=payload,
        metadata=k8s_client.V1ObjectMeta(
            name=name,
            namespace=namespace,
            owner_references=owner_refs,
        ),
    )

    return K8sSecret(
        name=v1_secret.metadata.name,
        namespace=v1_secret.metadata.namespace,
        cluster=cluster_id or DEFAULT_K8S_CLUSTER,
        manifest=Box(sanitizer(v1_secret)),
    )


def __create_ini_style_config(config: dict[str, dict[str, Any]]) -> str:
    def _stringify_bool(value: Any) -> str:
        """Converts booleans to a rclone compliant values."""
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    parser = ConfigParser(interpolation=None)

    for remote in config:
        parser.add_section(remote)
        for k, v in config[remote].items():
            parser.set(remote, k, _stringify_bool(v))

    output = StringIO()
    parser.write(output)
    # NOTE: If you do not flush the contents of the file may show up too late
    # for commands that expect to have the config present.
    output.flush()
    return output.getvalue()
