"""Models for the k8s watcher."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Self

from box import Box
from kr8s import APIObject
from kr8s._api import Api

from renku_data_services.k8s.constants import ClusterId

K8sPatch = dict[str, Any]
K8sPatches = K8sPatch | list[K8sPatch]


class K8sObjectMeta:
    """Metadata about a k8s object."""

    def __init__(
        self,
        name: str,
        namespace: str | None,
        cluster: ClusterId,
        gvk: GVK,
        user_id: str | None = None,
    ) -> None:
        self.name = name
        if namespace is not None and len(namespace) == 0:
            self.namespace = None
        else:
            self.namespace = namespace
        self.cluster = cluster
        self.gvk = gvk
        self.user_id = user_id

    def namespaced(self) -> bool:
        """Whether the resource is namespaced (true) or cluster-scoped (false)."""
        return self.namespace is not None

    def with_manifest(self, manifest: dict[str, Any]) -> K8sObject:
        """Convert to a full k8s object."""
        return K8sObject(
            name=self.name,
            namespace=self.namespace,
            cluster=self.cluster,
            gvk=self.gvk,
            manifest=Box(manifest),
            user_id=self.user_id,
        )

    def to_filter(self, label_selector: dict[str, str] | None = None) -> K8sObjectFilter:
        """Convert the metadata to a filter used when listing resources."""
        return K8sObjectFilter(
            gvk=self.gvk,
            namespace=self.namespace,
            cluster=self.cluster,
            name=self.name,
            user_id=self.user_id,
            label_selector=label_selector,
        )

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(name={self.name}, namespace={self.namespace}, cluster={self.cluster}, "
            f"gvk={self.gvk}, user_id={self.user_id})"
        )


class K8sObject(K8sObjectMeta):
    """Represents an object in k8s."""

    def __init__(
        self,
        name: str,
        namespace: str | None,
        cluster: ClusterId,
        gvk: GVK,
        manifest: Box,
        user_id: str | None = None,
    ) -> None:
        super().__init__(name, namespace, cluster, gvk, user_id)
        self.manifest = manifest

    def to_api_object(self, api: Api) -> APIObject:
        """Convert a regular k8s object to an api object for kr8s."""
        _singular = self.gvk.kind.lower()
        _plural = f"{_singular}s" if _singular[-1] != "s" else f"{_singular}es"
        _endpoint = _plural

        class _APIObj(APIObject):
            kind = self.gvk.kind
            version = self.gvk.group_version
            singular = _singular
            plural = _plural
            endpoint = _endpoint
            namespaced = self.namespaced()

        return _APIObj(resource=self.manifest, namespace=self.namespace, api=api)


@dataclass
class K8sObjectFilter:
    """Parameters used when filtering resources from the cache or k8s."""

    gvk: GVK
    name: str | None = None
    namespace: str | None = None
    cluster: ClusterId | None = None
    label_selector: dict[str, str] | None = None
    user_id: str | None = None


GVK_CORE_GROUP: Final[str] = "core"


@dataclass(kw_only=True, frozen=True)
class GVK:
    """The information about the group, version and kind of a K8s object."""

    kind: str
    version: str
    group: str | None = None

    @property
    def group_version(self) -> str:
        """Get the group and version joined by '/'."""
        if self.group is None or self.group.lower() == GVK_CORE_GROUP:
            return self.version
        return f"{self.group}/{self.version}"

    @property
    def kr8s_kind(self) -> str:
        """Returns the fully qualified kind string for this filter for kr8s.

        Note: This exists because kr8s has some methods where it only allows you to specify 'kind' and then has
        weird logic to split that. This method is essentially the reverse of the kr8s logic so we can hand it a
        string it will accept.
        """
        if self.group is None or self.group.lower() == GVK_CORE_GROUP:
            # e.g. pod/v1
            return f"{self.kind.lower()}/{self.version}"
        # e.g. buildrun.shipwright.io/v1beta1
        return f"{self.kind.lower()}.{self.group_version}"

    @classmethod
    def from_kr8s_object(cls, kr8s_obj: type[APIObject] | APIObject) -> Self:
        """Extract GVK from a kr8s object."""
        if "/" in kr8s_obj.version:
            grp_version_split = kr8s_obj.version.split("/", maxsplit=1)
            grp = grp_version_split[0]
            version = grp_version_split[1]
        else:
            grp = None
            version = kr8s_obj.version
        return cls(
            kind=kr8s_obj.kind,
            group=grp,
            version=version,
        )
