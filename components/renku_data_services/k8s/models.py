"""Models for the k8s watcher."""

from __future__ import annotations

from base64 import b64encode
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, Self, cast

import kubernetes
from box import Box
from kr8s._api import Api
from kr8s.asyncio.objects import APIObject
from kr8s.objects import Secret
from kubernetes.client import V1PriorityClass, V1ResourceQuota, V1Secret

from renku_data_services.errors import ProgrammingError, errors
from renku_data_services.k8s.constants import DUMMY_TASK_RUN_USER_ID, ClusterId

_kubernetes_client = kubernetes.client.ApiClient()
sanitizer = _kubernetes_client.sanitize_for_serialization


def _deserializer(data: Any, klass: type) -> Any:
    """Deserialise k8s object into a klass instance."""

    # NOTE: There is unfortunately no other way around this, this is the only thing that will
    # properly handle snake case - camel case conversions and a bunch of other things.
    obj = _kubernetes_client._ApiClient__deserialize(data, klass)
    if not isinstance(obj, klass):
        raise errors.ProgrammingError(message=f"Could not convert from a kr8s object to a {klass}")

    return obj


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

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(name={self.name}, namespace={self.namespace}, cluster={self.cluster}, "
            f"gvk={self.gvk}, user_id={self.user_id}, manifest={self.manifest})"
        )


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
    ) -> None:
        super().__init__(
            name=name,
            namespace=namespace,
            cluster=cluster,
            gvk=gvk,
            manifest=manifest,
            user_id=user_id,
        )

    def __repr__(self) -> str:
        # We hide the manifest to prevent leaking secrets
        return (
            f"{self.__class__.__name__}(name={self.name}, namespace={self.namespace}, cluster={self.cluster}, "
            f"gvk={self.gvk}, user_id={self.user_id})"
        )

    @classmethod
    def from_k8s_object(cls, k8s_object: K8sObject) -> K8sSecret:
        """Convert a k8s object to a K8sSecret object."""
        assert k8s_object.namespace is not None

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
            gvk=GVK(version=Secret.version, kind="Secret"),
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

    def __b64encode_values(self, stringData: dict[str, Any], new_data: dict[str, str]) -> None:
        for k, v in stringData.items():
            if k in new_data:
                raise ProgrammingError(
                    message=f"Patching a secret with both stringData and data and conflicting key {k}."
                )
            new_data[k] = b64encode(str(v).encode("utf-8")).decode("utf-8")

    def to_patch(self) -> list[dict[str, Any]]:
        """Create a rfc6902 patch that would take an existing secret and patch it to this state."""
        secretData = self.manifest.get("data") or {}
        stringData = self.manifest.get("stringData")
        if stringData:
            secretData = secretData.copy()
            self.__b64encode_values(stringData, secretData)

        patch = [
            {"op": "replace", "path": "/data", "value": secretData},
            {"op": "replace", "path": "/type", "value": self.manifest.get("type", "Opaque")},
        ]
        if "metadata" not in self.manifest:
            return patch
        if "labels" in self.manifest.metadata:
            patch.append(
                {"op": "replace", "path": "/metadata/labels", "value": self.manifest.metadata.labels},
            )
        if "annotations" in self.manifest.metadata:
            patch.append(
                {"op": "replace", "path": "/metadata/annotations", "value": self.manifest.metadata.annotations},
            )
        if "ownerReferences" in self.manifest.metadata:
            patch.append(
                {"op": "replace", "path": "/metadata/ownerReferences", "value": self.manifest.metadata.ownerReferences},
            )
        # We never create 'finalizers' nor 'managedFields', so we do not patch them.
        return patch


class K8sResourceQuota(K8sObject):
    """Represents a ResourceQuota in k8s."""

    def __init__(
        self,
        name: str,
        namespace: str,
        cluster: ClusterId,
        manifest: Box | None = None,
    ) -> None:
        super().__init__(
            name=name,
            namespace=namespace,
            cluster=cluster,
            gvk=GVK(kind="ResourceQuota", version="v1"),
            manifest=Box() if manifest is None else manifest,
        )

    @classmethod
    def from_k8s_object(cls, k8s_object: K8sObject) -> K8sResourceQuota:
        """Convert a k8s object to a K8sResourceQuota object."""
        assert k8s_object.namespace is not None

        return K8sResourceQuota(
            name=k8s_object.name,
            namespace=k8s_object.namespace,
            cluster=k8s_object.cluster,
            manifest=k8s_object.manifest,
        )

    @classmethod
    def get_filter(cls, label_selector: dict[str, str], namespace: str, cluster_id: ClusterId) -> K8sObjectFilter:
        """Return a filter to list K8s objects."""

        return K8sObjectFilter(
            gvk=GVK(kind="ResourceQuota", version="v1"),
            namespace=namespace,
            label_selector=label_selector,
            cluster=cluster_id,
        )

    def to_v1_resource_quota(self) -> V1ResourceQuota:
        """Convert a K8sResouceQuota to a V1ResourceQuota."""
        return _deserializer(self.manifest.to_dict(), V1ResourceQuota)


class K8sPriorityClass(K8sObject):
    """Represents a PriorityClass in k8s."""

    def __init__(
        self,
        name: str,
        cluster: ClusterId,
        manifest: Box | None = None,
    ) -> None:
        super().__init__(
            name=name,
            namespace=None,
            cluster=cluster,
            gvk=GVK(kind="PriorityClass", version="v1", group="scheduling.k8s.io"),
            manifest=Box() if manifest is None else manifest,
        )

    @classmethod
    def from_k8s_object(cls, k8s_object: K8sObject) -> K8sPriorityClass:
        """Convert a k8s object to a K8sPriorityClass object."""
        assert k8s_object.namespace is None

        return K8sPriorityClass(
            name=k8s_object.name,
            cluster=k8s_object.cluster,
            manifest=k8s_object.manifest,
        )

    def to_v1_priority_class(self) -> V1PriorityClass:
        """Convert a K8sResouceQuota to a V1ResourceQuota."""
        return _deserializer(self.manifest.to_dict(), V1PriorityClass)


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


class DeletePropagationPolicy(StrEnum):
    """Propagation policy when deleting objects in K8s."""

    foreground = "Foreground"
    background = "Background"
