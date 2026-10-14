"""Business logic for user endpoints."""

from base64 import b64decode, b64encode
from datetime import datetime
from hashlib import sha256

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import ssh

from renku_data_services.errors import errors
from renku_data_services.secrets.models import SecretKind, SecretPatch, UnsavedSecret
from renku_data_services.users import apispec
from renku_data_services.users.models import UnsavedSSHKey

SUPPORTED_SSH_KEY_TYPES = {
    "ssh-ed25519",
    "ssh-rsa",
    "ecdsa-sha2-nistp256",
    "ecdsa-sha2-nistp384",
    "ecdsa-sha2-nistp521",
}


def _validate_expiration_timestamp(expiration_timestamp: datetime | None) -> None:
    if expiration_timestamp is not None and expiration_timestamp.tzinfo is None:
        raise errors.ValidationError(message="The expiration_timestamp has to contain timezone information.")


def validate_unsaved_secret(body: apispec.SecretPost) -> UnsavedSecret:
    """Validate a new secret to be created."""
    _validate_expiration_timestamp(body.expiration_timestamp)
    return UnsavedSecret(
        name=body.name,
        secret_value=body.value,
        kind=SecretKind(body.kind.value),
        expiration_timestamp=body.expiration_timestamp,
        default_filename=body.default_filename,
    )


def validate_secret_patch(patch: apispec.SecretPatch) -> SecretPatch:
    """Validate the update to a secret."""
    _validate_expiration_timestamp(patch.expiration_timestamp)
    return SecretPatch(
        name=patch.name,
        secret_value=patch.value,
        expiration_timestamp=patch.expiration_timestamp,
        default_filename=patch.default_filename,
    )


def fingerprint_ssh_public_key(public_key: str) -> str | None:
    """Return the OpenSSH-compatible fingerprint of an SSH public key, or None if it cannot be parsed.

    Matches `ssh-keygen -l`: SHA256 over the decoded key blob, base64 without padding, `SHA256:` prefixed.
    It is the identity of a key and is what the internal authorize endpoint looks up.
    """
    raw = public_key.strip()
    parts = raw.split()
    if len(parts) < 2 or parts[0] not in SUPPORTED_SSH_KEY_TYPES:
        return None
    try:
        ssh.load_ssh_public_key(raw.encode())
        blob = b64decode(parts[1])
    except ValueError:
        return None
    return "SHA256:" + b64encode(sha256(blob).digest()).decode().rstrip("=")


def validate_unsaved_ssh_key(public_key: str, name: str | None) -> UnsavedSSHKey:
    """Validate a new SSH public key and canonicalize it."""
    raw = public_key.strip()
    fingerprint = fingerprint_ssh_public_key(raw)
    if fingerprint is None:
        raise errors.ValidationError(message="The provided SSH public key is not valid.")
    parsed = ssh.load_ssh_public_key(raw.encode())
    canonical = parsed.public_bytes(
        encoding=serialization.Encoding.OpenSSH,
        format=serialization.PublicFormat.OpenSSH,
    ).decode()
    clean_name = name.strip() if name and name.strip() else None
    return UnsavedSSHKey(public_key=canonical, key_type=canonical.split()[0], fingerprint=fingerprint, name=clean_name)
