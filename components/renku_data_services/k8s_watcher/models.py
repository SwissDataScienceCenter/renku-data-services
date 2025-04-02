"""Models for the k8s watcher."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, NewType

ClusterId = NewType("ClusterId", str)


@dataclass(eq=True, frozen=True, kw_only=True)
class K8sObjectMeta:
    """Metadata about a k8s object."""

    name: str
    namespace: str
    cluster: ClusterId
    kind: str
    version: str
    user_id: str

    def with_manifest(self, manifest: dict[str, Any]) -> K8sObject:
        """Convert to a full k8s object."""
        return K8sObject(
            name=self.name,
            namespace=self.namespace,
            cluster=self.cluster,
            kind=self.kind,
            version=self.version,
            manifest=manifest,
            user_id=self.user_id,
        )

    def to_list_filter(self) -> ListFilter:
        """Convert the metadata to a filter used when listing resources."""
        return ListFilter(
            kind=self.kind,
            namespace=self.namespace,
            cluster=self.cluster,
            name=self.name,
            version=self.version,
        )


@dataclass(eq=True, frozen=True, kw_only=True)
class K8sObject(K8sObjectMeta):
    """A full k8s object with metadata and a manifest."""

    manifest: dict[str, Any]

    @property
    def meta(self) -> K8sObjectMeta:
        """Extract just the metadata."""
        return K8sObjectMeta(
            name=self.name,
            namespace=self.namespace,
            cluster=self.cluster,
            kind=self.kind,
            version=self.version,
            user_id=self.user_id,
        )


@dataclass
class ListFilter:
    """Parameters used when filtering resources from the cache or k8s."""

    kind: str
    name: str | None = None
    namespace: str | None = None
    cluster: ClusterId | None = None
    version: str | None = None
    label_selector: dict[str, str] | None = None
