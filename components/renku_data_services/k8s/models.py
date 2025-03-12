"""Models for the k8s watcher."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, NewType

from box import Box
from kr8s._api import Api
from kr8s.asyncio.objects import APIObject

ClusterId = NewType("ClusterId", str)


class K8sObjectMeta:
    """Metadata about a k8s object."""

    def __init__(
        self,
        name: str,
        namespace: str,
        cluster: ClusterId,
        kind: str,
        version: str,
        user_id: str | None = None,
        endpoint: str | None = None,
        singular: str | None = None,
        plural: str | None = None,
        namespaced: bool = True,
    ) -> None:
        self.name = name
        self.namespace = namespace
        self.cluster = cluster
        self.kind = kind
        self.version = version
        self.user_id = user_id

        # calculate kr8s properties if not provided
        if singular is None:
            singular = self.kind.lower()
        self.singular = singular
        if plural is None:
            plural = f"{singular}s"
        self.plural = plural
        if endpoint is None:
            endpoint = plural
        self.endpoint = endpoint
        self.namespaced = namespaced

    def with_manifest(self, manifest: dict[str, Any]) -> K8sObject:
        """Convert to a full k8s object."""
        return K8sObject(
            name=self.name,
            namespace=self.namespace,
            cluster=self.cluster,
            kind=self.kind,
            version=self.version,
            manifest=Box(manifest),
            user_id=self.user_id,
        )

    def to_filter(self) -> K8sObjectFilter:
        """Convert the metadata to a filter used when listing resources."""
        return K8sObjectFilter(
            kind=self.kind,
            namespace=self.namespace,
            cluster=self.cluster,
            name=self.name,
            version=self.version,
            user_id=self.user_id,
        )

    def __repr__(self) -> str:
        return (
            f"K8sObject(name={self.name}, namespace={self.namespace},cluster={self.cluster},"
            f"version={self.version},kind={self.kind},user_id={self.user_id})"
        )


class K8sObject(K8sObjectMeta):
    """Represents an object in k8s."""

    def __init__(
        self,
        name: str,
        namespace: str,
        cluster: ClusterId,
        kind: str,
        version: str,
        manifest: Box,
        user_id: str | None = None,
        endpoint: str | None = None,
        singular: str | None = None,
        plural: str | None = None,
        namespaced: bool = True,
    ) -> None:
        super().__init__(name, namespace, cluster, kind, version, user_id, endpoint, singular, plural, namespaced)
        self.manifest = manifest

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
            singular=self.singular,
            plural=self.plural,
            endpoint=self.endpoint,
            namespaced=self.namespaced,
        )

    def __repr__(self) -> str:
        return super().__repr__()

    def to_api_object(self, api: Api) -> APIObject:
        """Convert a regular k8s object to an api object."""

        class _APIObj(APIObject):
            kind = self.meta.kind
            version = self.meta.version
            singular = self.meta.singular
            plural = self.meta.plural
            endpoint = self.meta.plural
            namespaced = self.meta.namespaced

        return _APIObj(resource=self.manifest, namespace=self.meta.namespace, api=api)


@dataclass
class K8sObjectFilter:
    """Parameters used when filtering resources from the cache or k8s."""

    kind: str
    name: str | None = None
    namespace: str | None = None
    cluster: ClusterId | None = None
    version: str | None = None
    label_selector: dict[str, str] | None = None
    user_id: str | None = None


@dataclass(eq=True, frozen=True)
class Cluster:
    """Representation of a k8s cluster."""

    id: ClusterId
    namespace: str
    api: Api
