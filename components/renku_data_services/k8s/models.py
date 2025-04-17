"""Models for the k8s watcher."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, NewType, Self, cast

from box import Box
from kr8s._api import Api
from kr8s._objects import APIObject

from renku_data_services.errors import errors

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

    def to_list_filter(self) -> ListFilter:
        """Convert the metadata to a filter used when listing resources."""
        return ListFilter(
            kind=self.kind,
            namespace=self.namespace,
            cluster=self.cluster,
            name=self.name,
            version=self.version,
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


@dataclass
class ListFilter:
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


@dataclass
class APIObjectInCluster:
    """An kr8s k8s object from a specific cluster."""

    obj: APIObject
    cluster: ClusterId

    @property
    def user_id(self) -> str | None:
        """Extract the user id from annotations."""
        user_id = user_id_from_api_object(self.obj)
        return user_id

    @property
    def meta(self) -> K8sObjectMeta:
        """Extract the metadata from an api object."""
        return K8sObjectMeta(
            name=self.obj.name,
            namespace=self.obj.namespace or "default",
            cluster=self.cluster,
            version=self.obj.version,
            kind=self.obj.kind,
            user_id=self.user_id,
        )

    def to_k8s_object(self) -> K8sObject:
        """Convert the api object to a regular k8s object."""
        if self.obj.name is None or self.obj.namespace is None:
            raise errors.ProgrammingError()
        return K8sObject(
            name=self.obj.name,
            namespace=self.obj.namespace,
            kind=self.obj.kind,
            version=self.obj.version,
            manifest=Box(self.obj.to_dict()),
            cluster=self.cluster,
            user_id=self.user_id,
        )

    @classmethod
    def from_k8s_object(cls, obj: K8sObject, api: Api | None = None) -> Self:
        """Convert a regular k8s object to an api object."""

        class _APIObj(APIObject):
            kind = obj.meta.kind
            version = obj.meta.version
            singular = obj.meta.singular
            plural = obj.meta.plural
            endpoint = obj.meta.plural
            namespaced = obj.meta.namespaced

        return cls(
            obj=_APIObj(
                resource=obj.manifest,
                namespace=obj.meta.namespace,
                api=api,
            ),
            cluster=obj.cluster,
        )


def user_id_from_api_object(obj: APIObject) -> str | None:
    """Get the user id from an api object."""
    match obj.kind.lower():
        case "jupyterserver":
            return cast(str, obj.metadata.labels["renku.io/userId"])
        case "amaltheasession":
            return cast(str, obj.metadata.labels["renku.io/safe-username"])
        case _:
            return None
