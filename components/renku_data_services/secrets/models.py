"""Base models for secrets."""

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

from kubernetes import client as k8s_client
from pydantic import BaseModel, Field
from ulid import ULID


class SecretKind(Enum):
    """Kind of secret. This should have the same values as users.apispec.SecretKind."""

    general = "general"
    storage = "storage"


class UnsavedSecret(BaseModel):
    """Secret objects not stored in the database."""

    name: str
    encrypted_value: bytes = Field(repr=False)
    encrypted_key: bytes = Field(repr=False)
    modification_date: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(microsecond=0), init=False)
    kind: SecretKind


class Secret(UnsavedSecret):
    """Secret object stored in the database."""

    id: ULID = Field()

    session_secret_ids: list[ULID]
    """List of session secret IDs where this user secret is used."""


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
