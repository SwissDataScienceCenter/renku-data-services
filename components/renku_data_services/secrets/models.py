"""Base models for secrets."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from cryptography.hazmat.primitives.asymmetric import rsa
from kubernetes import client as k8s_client
from ulid import ULID

from renku_data_services.app_config import logging
from renku_data_services.utils.cryptography import (
    decrypt_rsa,
    decrypt_string,
    encrypt_rsa,
    encrypt_string,
    generate_random_encryption_key,
)

logger = logging.getLogger(__name__)


class SecretKind(StrEnum):
    """Kind of secret. This should have the same values as users.apispec.SecretKind."""

    general = "general"
    storage = "storage"


@dataclass(frozen=True, eq=True, kw_only=True)
class Secret:
    """Secret object stored in the database."""

    id: ULID
    name: str
    default_filename: str
    encrypted_value: bytes = field(repr=False)
    encrypted_key: bytes = field(repr=False)
    kind: SecretKind
    modification_date: datetime

    session_secret_slot_ids: list[ULID]
    """List of session secret slot IDs where this user secret is used."""

    data_connector_ids: list[ULID]
    """List of data connector IDs where this user secret is used."""

    def update_encrypted_value(self, encrypted_value: bytes, encrypted_key: bytes) -> Secret:
        """Returns a new secret instance with updated encrypted_value and encrypted_key."""
        return Secret(
            id=self.id,
            name=self.name,
            default_filename=self.default_filename,
            encrypted_value=encrypted_value,
            encrypted_key=encrypted_key,
            kind=self.kind,
            modification_date=self.modification_date,
            session_secret_slot_ids=self.session_secret_slot_ids,
            data_connector_ids=self.data_connector_ids,
        )

    async def rotate_single_encryption_key(
        self, user_id: str, new_key: rsa.RSAPrivateKey, old_key: rsa.RSAPrivateKey
    ) -> Secret | None:
        """Rotate a single secret in place."""
        # try using new key first as a sanity check, in case it was already rotated
        try:
            _ = decrypt_rsa(new_key, self.encrypted_key)
        except ValueError:
            pass
        else:
            return None  # could decrypt with new key, nothing to do

        try:
            decryption_key = decrypt_rsa(old_key, self.encrypted_key)
            decrypted_value = decrypt_string(decryption_key, user_id, self.encrypted_value).encode()
            new_encryption_key = generate_random_encryption_key()
            encrypted_value = encrypt_string(new_encryption_key, user_id, decrypted_value.decode())
            encrypted_key = encrypt_rsa(new_key.public_key(), new_encryption_key)
            return self.update_encrypted_value(encrypted_value=encrypted_value, encrypted_key=encrypted_key)
        except Exception as e:
            logger.error(f"Couldn't decrypt secret {self.name}({self.id}): {e}")
            return None


@dataclass
class OwnerReference:
    """A kubernetes owner reference."""

    apiVersion: str
    kind: str
    name: str
    uid: str

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> OwnerReference:
        """Create an owner reference from a dict."""
        return cls(apiVersion=data["apiVersion"], kind=data["kind"], name=data["name"], uid=data["uid"])

    def to_k8s(self) -> k8s_client.V1OwnerReference:
        """Return k8s OwnerReference."""
        return k8s_client.V1OwnerReference(
            api_version=self.apiVersion,
            kind=self.kind,
            name=self.name,
            uid=self.uid,
            controller=True,
        )


@dataclass(frozen=True, eq=True, kw_only=True)
class UnsavedSecret:
    """Model to request the creation of a new user secret."""

    name: str
    default_filename: str | None
    secret_value: str = field(repr=False)
    kind: SecretKind


@dataclass(frozen=True, eq=True, kw_only=True)
class SecretPatch:
    """Model for changes requested on a user secret."""

    name: str | None
    default_filename: str | None
    secret_value: str | None = field(repr=False)
    expiration_timestamp: datetime | None
