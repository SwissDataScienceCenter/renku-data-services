"""Models for the k8s watcher."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Self, cast

from box import Box
from kr8s._api import Api
from kr8s.asyncio.objects import APIObject
from ulid import ULID

from renku_data_services.base_models import APIUser
from renku_data_services.errors import MissingResourceError, errors
from renku_data_services.k8s.constants import DUMMY_TASK_RUN_USER_ID, ClusterId
from renku_data_services.notebooks.cr_amalthea_session import TlsSecret

if TYPE_CHECKING:
    from renku_data_services.crc.db import ClusterRepository
    from renku_data_services.notebooks.config.dynamic import _SessionIngress


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
            f"K8sObject(name={self.name}, namespace={self.namespace}, cluster={self.cluster}, "
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
        return super().__repr__()

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


@dataclass
class K8sObjectFilter:
    """Parameters used when filtering resources from the cache or k8s."""

    gvk: GVK
    name: str | None = None
    namespace: str | None = None
    cluster: ClusterId | None = None
    label_selector: dict[str, str] | None = None
    user_id: str | None = None


@dataclass(eq=True, frozen=True)
class Cluster:
    """Representation of a k8s cluster."""

    id: ClusterId
    namespace: str
    api: Api

    def with_api_object(self, obj: APIObject) -> APIObjectInCluster:
        """Create an API object associated with the cluster."""
        return APIObjectInCluster(obj, self.id)

    async def get_storage_class(
        self, user: APIUser, cluster_repo: ClusterRepository, default_storage_class: str | None
    ) -> str | None:
        """Get the default storage class for the cluster."""
        try:
            cluster = await cluster_repo.select(user, ULID.from_str(self.id))
            storage_class = cluster.session_storage_class
        except (MissingResourceError, ValueError) as _e:
            storage_class = default_storage_class

        return storage_class

    async def get_ingress_parameters(
        self, user: APIUser, cluster_repo: ClusterRepository, main_ingress: _SessionIngress, server_name: str
    ) -> tuple[str, str, str, str, TlsSecret | None, dict[str, str]]:
        """Returns the ingress parameters of the cluster."""
        tls_name = None

        try:
            cluster = await cluster_repo.select(user, ULID.from_str(self.id))

            host = cluster.session_host
            base_server_path = f"{cluster.session_path}/{server_name}"
            base_server_url = f"{cluster.session_protocol.value}://{host}:{cluster.session_port}{base_server_path}"
            base_server_https_url = base_server_url
            tls_name = cluster.session_tls_secret_name
            ingress_annotations = cluster.session_ingress_annotations
        except (MissingResourceError, ValueError) as _e:
            # Fallback to global, main cluster parameters
            host = main_ingress.host
            base_server_path = main_ingress.base_path(server_name)
            base_server_url = main_ingress.base_url(server_name)
            base_server_https_url = main_ingress.base_url(server_name, force_https=True)
            ingress_annotations = main_ingress.annotations

            if main_ingress.tls_secret is not None:
                tls_name = main_ingress.tls_secret

        tls_secret = None if tls_name is None else TlsSecret(adopt=False, name=tls_name)

        return base_server_path, base_server_url, base_server_https_url, host, tls_secret, ingress_annotations


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
        match self.obj.singular:
            case "jupyterserver":
                return cast(str, self.obj.metadata.labels["renku.io/userId"])
            case "amaltheasession":
                return cast(str, self.obj.metadata.labels["renku.io/safe-username"])
            case "buildrun":
                return cast(str, self.obj.metadata.labels["renku.io/safe-username"])

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
