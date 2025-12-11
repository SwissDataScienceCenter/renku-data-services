"""Business logic for user endpoints."""

from datetime import datetime

from renku_data_services.secrets.models import SecretKind, SecretPatch, UnsavedSecret
from renku_data_services.users import apispec


def _validate_expiration_timestamp(expiration_timestamp: datetime | None) -> bool:
    return expiration_timestamp is None or expiration_timestamp.tzinfo is not None


def validate_unsaved_secret(body: apispec.SecretPost) -> UnsavedSecret:
    """Validate a new secret to be created."""
    if _validate_expiration_timestamp(body.expiration_timestamp):
        return UnsavedSecret(
            name=body.name,
            secret_value=body.value,
            kind=SecretKind(body.kind.value),
            expiration_timestamp=body.expiration_timestamp,
            default_filename=body.default_filename,
        )
    raise ValueError("Expiration timestamp must be specified with a time zone")


def validate_secret_patch(patch: apispec.SecretPatch) -> SecretPatch:
    """Validate the update to a secret."""
    return SecretPatch(
        name=patch.name,
        secret_value=patch.value,
        expiration_timestamp=patch.expiration_timestamp,
        default_filename=patch.default_filename,
    )
