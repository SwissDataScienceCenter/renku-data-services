"""Models for the k8s watcher."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Self, cast

import kubernetes
from box import Box
from kr8s._api import Api
from kr8s.asyncio.objects import APIObject
from kr8s.objects import Secret
from kubernetes_asyncio.client import V1Secret

from renku_data_services.errors import errors
from renku_data_services.k8s.constants import DUMMY_TASK_RUN_USER_ID, ClusterId

sanitizer = kubernetes.client.ApiClient().sanitize_for_serialization


class K8sObjectMeta:
    """Metadata about a k8s object."""

    def __init__(
        self,
        name: str,
        namespace: str,
        cluster: ClusterId,
        gvk: GVK,
        user_id: str | None = None,
        namespaced: bool = True,
    ) -> None:
        self.name = name
        self.namespace = namespace
        self.cluster = cluster
        self.gvk = gvk
        self.user_id = user_id

        self.namespaced = namespaced

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

    def to_filter(self) -> K8sObjectFilter:
        """Convert the metadata to a filter used when listing resources."""
        return K8sObjectFilter(
            gvk=self.gvk,
            namespace=self.namespace,
            cluster=self.cluster,
            name=self.name,
            user_id=self.user_id,
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
        namespace: str,
        cluster: ClusterId,
        gvk: GVK,
        manifest: Box,
        user_id: str | None = None,
        namespaced: bool = True,
    ) -> None:
        super().__init__(name, namespace, cluster, gvk, user_id, namespaced)
        self.manifest = manifest

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(name={self.name}, namespace={self.namespace}, cluster={self.cluster}, "
            f"gvk={self.gvk}, manifest={self.manifest}, user_id={self.user_id})"
        )

    def to_api_object(self, api: Api) -> APIObject:
        """Convert a regular k8s object to an api object for kr8s."""

        _singular = self.gvk.kind.lower()
        _plural = f"{_singular}s"
        _endpoint = _plural

        class _APIObj(APIObject):
            kind = self.gvk.kind
            version = self.gvk.group_version
            singular = _singular
            plural = _plural
            endpoint = _endpoint
            namespaced = self.namespaced

        return _APIObj(resource=self.manifest, namespace=self.namespace, api=api)


class K8sSecret(K8sObject):
    """Represents a secret in k8s."""

    def __init__(
        self,
        name: str,
        namespace: str,
        cluster: ClusterId,
        gvk: GVK,
        manifest: Box,
        user_id: str | None = None,
        namespaced: bool = True,
    ) -> None:
        super().__init__(name, namespace, cluster, gvk, manifest, user_id, namespaced)

    def __repr__(self) -> str:
        # We hide the manifest to prevent leaking secrets
        return (
            f"{self.__class__.__name__}(name={self.name}, namespace={self.namespace}, cluster={self.cluster}, "
            f"gvk={self.gvk}, user_id={self.user_id})"
        )

    @classmethod
    def from_k8s_object(cls, k8s_object: K8sObject) -> K8sSecret:
        """Convert a k8s object to a K8sSecret object."""
        return K8sSecret(
            name=k8s_object.name,
            namespace=k8s_object.namespace,
            cluster=k8s_object.cluster,
            gvk=k8s_object.gvk,
            manifest=k8s_object.manifest,
        )

    @classmethod
    def from_v1_secret(cls, secret: V1Secret, cluster: ClusterConnection) -> K8sSecret:
        """Convert a V1Secret object to a K8sSecret object."""
        assert secret.metadata is not None

        return K8sSecret(
            name=secret.metadata.name,
            namespace=cluster.namespace,
            cluster=cluster.id,
            gvk=GVK(group="core", version=Secret.version, kind="Secret"),
            manifest=Box(sanitizer(secret)),
        )

    def to_v1_secret(self) -> V1Secret:
        """Convert a K8sSecret to a V1Secret object."""
        return V1Secret(
            metadata=self.manifest.metadata,
            data=self.manifest.get("data", {}),
            string_data=self.manifest.get("stringData", {}),
            type=self.manifest.get("type"),
        )


@dataclass
class K8sObjectFilter:
    """Parameters used when filtering resources from the cache or k8s."""

    gvk: GVK
    name: str | None = None
    namespace: str | None = None
    cluster: ClusterId | None = None
    label_selector: dict[str, str] | None = None
    user_id: str | None = None


@dataclass(frozen=True, eq=True, kw_only=True)
class ClusterConnection:
    """K8s Cluster wrapper."""

    id: ClusterId
    namespace: str
    api: Api

    def with_api_object(self, obj: APIObject) -> APIObjectInCluster:
        """Create an API object associated with the cluster."""
        return APIObjectInCluster(obj, self.id)


@dataclass(kw_only=True, frozen=True)
class GVK:
    """The information about the group, version and kind of a K8s object."""

    kind: str
    version: str
    group: str | None = None

    @property
    def group_version(self) -> str:
        """Get the group and version joined by '/'."""
        if self.group == "core" or self.group is None:
            return self.version
        return f"{self.group}/{self.version}"

    @property
    def kr8s_kind(self) -> str:
        """Returns the fully qualified kind string for this filter for kr8s.

        Note: This exists because kr8s has some methods where it only allows you to specify 'kind' and then has
        weird logic to split that. This method is essentially the reverse of the kr8s logic so we can hand it a
        string it will accept.
        """
        if self.group is None:
            # e.g. pod/v1
            return f"{self.kind.lower()}/{self.version}"
        # e.g. buildrun.shipwright.io/v1beta1
        return f"{self.kind.lower()}.{self.group_version}"

    @classmethod
    def from_kr8s_object(cls, kr8s_obj: type[APIObject] | APIObject) -> Self:
        """Extract GVK from a kr8s object."""
        if "/" in kr8s_obj.version:
            grp_version_split = kr8s_obj.version.split("/")
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


@dataclass
class APIObjectInCluster:
    """A kr8s k8s object from a specific cluster."""

    obj: APIObject
    cluster: ClusterId

    @property
    def user_id(self) -> str | None:
        """Extract the user id from annotations."""
        labels = cast(dict[str, str], self.obj.metadata.get("labels", {}))
        match self.obj.singular:
            case "jupyterserver":
                return labels.get("renku.io/userId", None)
            case "amaltheasession":
                return labels.get("renku.io/safe-username", None)
            case "buildrun":
                return labels.get("renku.io/safe-username", None)
            case "taskrun":
                return DUMMY_TASK_RUN_USER_ID
            case _:
                return None

    @property
    def meta(self) -> K8sObjectMeta:
        """Extract the metadata from an api object."""
        return K8sObjectMeta(
            name=self.obj.name,
            namespace=self.obj.namespace or "default",
            cluster=self.cluster,
            gvk=GVK.from_kr8s_object(self.obj),
            user_id=self.user_id,
        )

    def to_k8s_object(self) -> K8sObject:
        """Convert the api object to a regular k8s object."""
        if self.obj.name is None or self.obj.namespace is None:
            raise errors.ProgrammingError()
        return K8sObject(
            name=self.obj.name,
            namespace=self.obj.namespace,
            gvk=GVK.from_kr8s_object(self.obj),
            manifest=Box(self.obj.to_dict()),
            cluster=self.cluster,
            user_id=self.user_id,
        )

    @classmethod
    def from_k8s_object(cls, obj: K8sObject, api: Api) -> Self:
        """Convert a regular k8s object to an api object."""

        return cls(
            obj=obj.to_api_object(api),
            cluster=obj.cluster,
        )
