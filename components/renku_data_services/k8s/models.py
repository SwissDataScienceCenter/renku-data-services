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
from kubernetes.client import V1Secret

from renku_data_services.errors import ProgrammingError, errors
from renku_data_services.k8s.constants import DUMMY_TASK_RUN_USER_ID, ClusterId

sanitizer = kubernetes.client.ApiClient().sanitize_for_serialization


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
            self.__namespace = None
        else:
            self.__namespace = namespace
        self.cluster = cluster
        self.gvk = gvk
        self.user_id = user_id

    @property
    def namespaced(self) -> bool:
        """Whether the resource is namespaced (true) or cluster-scoped (false)."""
        return self.namespace is not None

    @property
    def namespace(self) -> str | None:
        """The namespace of the k8s object."""
        return self.__namespace

    def with_manifest(self, manifest: dict[str, Any]) -> K8sObject:
        """Convert to a full k8s object."""
        if not self.namespace:
            raise errors.ValidationError(
                message=f"Namespaced k8s objects have to have a defined namespace, got {self.namespace}"
            )
        return K8sObject(
            name=self.name,
            namespace=self.namespace,
            cluster=self.cluster,
            gvk=self.gvk,
            manifest=Box(manifest),
            user_id=self.user_id,
        )

    def with_cluster_scoped_manifest(self, manifest: dict[str, Any]) -> ClusterScopedK8sObject:
        """Convert to a full k8s cluster scoped object."""
        if self.namespace is not None:
            raise errors.ValidationError(
                message=f"Cluster scoped k8s objects do not have a defined namespace, got {self.namespace}"
            )
        return ClusterScopedK8sObject(
            name=self.name,
            cluster=self.cluster,
            gvk=self.gvk,
            manifest=Box(manifest),
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


def _convert_to_api_object(api: Api, obj: K8sObject | ClusterScopedK8sObject) -> APIObject:
    """Convert a regular k8s object to an api object for kr8s."""
    _singular = obj.gvk.kind.lower()
    _plural = f"{_singular}s" if _singular[-1] != "s" else f"{_singular}es"
    _endpoint = _plural

    class _APIObj(APIObject):
        kind = obj.gvk.kind
        version = obj.gvk.group_version
        singular = _singular
        plural = _plural
        endpoint = _endpoint
        namespaced = obj.namespaced

    return _APIObj(resource=obj.manifest, namespace=obj.namespace, api=api)


class K8sObject(K8sObjectMeta):
    """Represents a namespaced object in k8s."""

    def __init__(
        self,
        name: str,
        namespace: str,
        cluster: ClusterId,
        gvk: GVK,
        manifest: Box,
        user_id: str | None = None,
    ) -> None:
        if len(namespace) == 0:
            raise errors.ValidationError(message="Cannot have a namespaced K8s object with a namespace set to ''")
        super().__init__(name, namespace, cluster, gvk, user_id)
        self.manifest = manifest
        self.__obj_namespace = namespace

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(name={self.name}, namespace={self.namespace}, cluster={self.cluster}, "
            f"gvk={self.gvk}, user_id={self.user_id})"
        )

    def to_api_object(self, api: Api) -> APIObject:
        """Convert a regular k8s object to an api object for kr8s."""
        return _convert_to_api_object(api, self)

    @property
    def namespace(self) -> str:
        """The namespace of the k8s object."""
        return self.__obj_namespace


class ClusterScopedK8sObject(K8sObjectMeta):
    """Represents a cluster-scoped K8s object."""

    def __init__(
        self,
        name: str,
        cluster: ClusterId,
        gvk: GVK,
        manifest: Box,
    ) -> None:
        super().__init__(
            name=name,
            namespace=None,
            cluster=cluster,
            gvk=gvk,
            user_id=None,
        )
        self.manifest = manifest

    def to_api_object(self, api: Api) -> APIObject:
        """Convert a regular k8s object to an api object for kr8s."""
        return _convert_to_api_object(api, self)

    @property
    def namespace(self) -> None:
        """Cluster scoped objects do not have a namespace."""
        return None


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
            secretData = self.manifest.data.copy()
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
