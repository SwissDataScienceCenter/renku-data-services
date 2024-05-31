"""Base models for secrets."""

from datetime import UTC, datetime

from kubernetes import client as k8s_client
from pydantic import BaseModel, Field


class Secret(BaseModel):
    """Secret objects."""

    name: str
    encrypted_value: bytes = Field(repr=False)
    encrypted_key: bytes = Field(repr=False)
    id: str | None = Field(default=None, init=False)
    modification_date: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(microsecond=0), init=False)


class OwnerReference(BaseModel):
    """A kubernetes owner reference."""

    apiVersion: str
    kind: str
    name: str
    uid: str

    def to_k8s(self) -> k8s_client.V1OwnerReference:
        """Return k8s OwnerReference."""
        return k8s_client.V1OwnerReference(
            api_version=self.apiVersion,
            kind=self.kind,
            name=self.name,
            uid=self.uid,
            controller=True,
        )
