"""Base models for secrets."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from kubernetes import client as k8s_client
from ulid import ULID


class SecretKind(StrEnum):
    """Kind of secret. This should have the same values as users.apispec.SecretKind."""

    general = "general"
    storage = "storage"


@dataclass(frozen=True, eq=True, kw_only=True)
class UnsavedSecret:
    """Secret objects not stored in the database."""

    name: str
    default_filename: str | None
    encrypted_value: bytes = field(repr=False)
    encrypted_key: bytes = field(repr=False)
    kind: SecretKind


@dataclass(frozen=True, eq=True, kw_only=True)
class Secret(UnsavedSecret):
    """Secret object stored in the database."""

    id: ULID
    default_filename: str
    modification_date: datetime

    session_secret_slot_ids: list[ULID]
    """List of session secret slot IDs where this user secret is used."""

    data_connector_ids: list[ULID]
    """List of data connector IDs where this user secret is used."""

    def update_encrypted_value(self, encrypted_value: bytes, encrypted_key: bytes) -> "Secret":
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


@dataclass
class OwnerReference:
    """A kubernetes owner reference."""

    apiVersion: str
    kind: str
    name: str
    uid: str

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> "OwnerReference":
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
class NewSecret:
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
