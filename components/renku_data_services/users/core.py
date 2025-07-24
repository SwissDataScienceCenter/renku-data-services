"""Business logic for user endpoints."""

from renku_data_services.secrets.models import SecretKind, SecretPatch, UnsavedSecret
from renku_data_services.users import apispec


def validate_unsaved_secret(body: apispec.SecretPost) -> UnsavedSecret:
    """Validate a new secret to be created."""
    secret_kind = SecretKind(body.kind.value)
    return UnsavedSecret(
        name=body.name,
        default_filename=body.default_filename,
        secret_value=body.value,
        kind=secret_kind,
    )


def validate_secret_patch(patch: apispec.SecretPatch) -> SecretPatch:
    """Validate the update to a secret."""
    return SecretPatch(
        name=patch.name,
        default_filename=patch.default_filename,
        secret_value=patch.value,
        expiration_timestamp=patch.expiration_timestamp,
    )
