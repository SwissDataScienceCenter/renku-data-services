"""Domain models for the application."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, Optional, Protocol, Self

from renku_data_services import errors
from renku_data_services.base_models import ResetType
from renku_data_services.k8s.constants import DEFAULT_K8S_CLUSTER, ClusterId
from renku_data_services.notebooks.cr_amalthea_session import TlsSecret


class ResourcesProtocol(Protocol):
    """Used to represent resource values present in a resource class or quota."""

    @property
    def cpu(self) -> float:
        """Cpu in fractional cores."""
        ...

    @property
    def gpu(self) -> int:
        """Number of GPUs."""
        ...

    @property
    def memory(self) -> int:
        """Memory in gigabytes."""
        ...

    @property
    def max_storage(self) -> Optional[int]:
        """Maximum allowable storage in gigabytes."""
        ...


class ResourcesCompareMixin:
    """A mixin that adds comparison operator support on ResourceClasses and Quotas."""

    def __compare(
        self,
        other: ResourcesProtocol,
        compare_func: Callable[[int | float, int | float], bool],
    ) -> bool:
        results = [
            compare_func(self.cpu, other.cpu),  # type: ignore[attr-defined]
            compare_func(self.memory, other.memory),  # type: ignore[attr-defined]
            compare_func(self.gpu, other.gpu),  # type: ignore[attr-defined]
        ]
        self_storage = getattr(self, "max_storage", 99999999999999999999999)
        other_storage = getattr(other, "max_storage", 99999999999999999999999)
        results.append(compare_func(self_storage, other_storage))
        return all(results)

    def __ge__(self, other: ResourcesProtocol) -> bool:
        return self.__compare(other, lambda x, y: x >= y)

    def __gt__(self, other: ResourcesProtocol) -> bool:
        return self.__compare(other, lambda x, y: x > y)

    def __lt__(self, other: ResourcesProtocol) -> bool:
        return self.__compare(other, lambda x, y: x < y)

    def __le__(self, other: ResourcesProtocol) -> bool:
        return self.__compare(other, lambda x, y: x <= y)


@dataclass(frozen=True, eq=True, kw_only=True)
class NodeAffinity:
    """Used to set the node affinity when scheduling sessions."""

    key: str
    required_during_scheduling: bool = False


@dataclass(frozen=True, eq=True, kw_only=True)
class UnsavedResourceClass(ResourcesCompareMixin):
    """Model for a resource class yet to be saved."""

    name: str
    cpu: float
    memory: int
    max_storage: int
    gpu: int
    default: bool = False
    default_storage: int = 1
    node_affinities: list[NodeAffinity] = field(default_factory=list)
    tolerations: list[str] = field(default_factory=list)


@dataclass(frozen=True, eq=True, kw_only=True)
class ResourceClass(ResourcesCompareMixin):
    """Resource class model."""

    name: str
    cpu: float
    memory: int
    max_storage: int
    gpu: int
    id: int
    resource_pool_id: int
    default: bool = False
    default_storage: int = 1
    matching: Optional[bool] = None
    node_affinities: list[NodeAffinity] = field(default_factory=list)
    tolerations: list[str] = field(default_factory=list)
    quota: str | None = None


@dataclass(frozen=True, eq=True, kw_only=True)
class ResourceClassPatch:
    """Model for changes requested on a resource class."""

    name: str | None = None
    cpu: float | None = None
    memory: int | None = None
    max_storage: int | None = None
    gpu: int | None = None
    default: bool | None = None
    default_storage: int | None = None
    node_affinities: list[NodeAffinity] | None = None
    tolerations: list[str] | None = None


@dataclass(frozen=True, eq=True, kw_only=True)
class ResourceClassPatchWithId(ResourceClassPatch):
    """Model for changes requested on a resource class from patching/putting a resource pool."""

    id: int


class GpuKind(StrEnum):
    """GPU kinds for k8s."""

    NVIDIA = "nvidia.com"
    AMD = "amd.com"


@dataclass(frozen=True, eq=True, kw_only=True)
class UnsavedQuota(ResourcesCompareMixin):
    """Model for a quota yet to be saved."""

    cpu: float
    memory: int
    gpu: int
    gpu_kind: GpuKind = GpuKind.NVIDIA

    def is_resource_class_compatible(self, rc: ResourceClass | UnsavedResourceClass) -> bool:
        """Determine if a resource class is compatible with the quota."""
        return rc <= self


@dataclass(frozen=True, eq=True, kw_only=True)
class Quota(ResourcesCompareMixin):
    """Quota model."""

    cpu: float
    memory: int
    gpu: int
    gpu_kind: GpuKind = GpuKind.NVIDIA
    id: str

    def is_resource_class_compatible(self, rc: ResourceClass | UnsavedResourceClass) -> bool:
        """Determine if a resource class is compatible with the quota."""
        return rc <= self


@dataclass(frozen=True, eq=True, kw_only=True)
class QuotaPatch:
    """Model for changes requested on a quota."""

    cpu: float | None = None
    memory: int | None = None
    gpu: int | None = None
    gpu_kind: GpuKind | None = None


class SessionProtocol(StrEnum):
    """Valid Session protocol values."""

    HTTP = "http"
    HTTPS = "https"


@dataclass(frozen=True, eq=True, kw_only=True)
class ClusterPatch:
    """K8s Cluster settings patch."""

    name: str | None
    config_name: str | None
    session_protocol: SessionProtocol | None
    session_host: str | None
    session_port: int | None
    session_path: str | None
    session_ingress_class_name: str | None
    session_ingress_annotations: dict[str, Any] | None
    session_tls_secret_name: str | None
    session_storage_class: str | None
    service_account_name: str | None


@dataclass(frozen=True, eq=True, kw_only=True)
class ClusterSettings:
    """K8s Cluster settings."""

    name: str
    config_name: str
    session_protocol: SessionProtocol
    session_host: str
    session_port: int
    session_path: str
    session_ingress_class_name: str | None = None
    session_ingress_annotations: dict[str, str]
    session_tls_secret_name: str
    session_storage_class: str | None
    service_account_name: str | None = None

    def to_cluster_patch(self) -> ClusterPatch:
        """Convert to ClusterPatch."""

        return ClusterPatch(
            name=self.name,
            config_name=self.config_name,
            session_protocol=self.session_protocol,
            session_host=self.session_host,
            session_port=self.session_port,
            session_path=self.session_path,
            session_ingress_class_name=self.session_ingress_class_name,
            session_ingress_annotations=self.session_ingress_annotations,
            session_tls_secret_name=self.session_tls_secret_name,
            session_storage_class=self.session_storage_class,
            service_account_name=self.service_account_name,
        )

    def get_storage_class(self) -> str | None:
        """Get the default storage class for the cluster."""

        return self.session_storage_class

    def get_ingress_parameters(
        self, server_name: str
    ) -> tuple[str, str, str, str, TlsSecret | None, str | None, dict[str, str]]:
        """Returns the ingress parameters of the cluster."""

        host = self.session_host
        base_server_path = f"{self.session_path}/{server_name}"
        if self.session_port in [80, 443]:
            # No need to specify the port in these cases. If we specify the port on https or http
            # when it is the usual port then the URL callbacks for authentication do not work.
            # I.e. if the callback is registered as https://some.host/link it will not work when a redirect
            # like https://some.host:443/link is used.
            base_server_url = f"{self.session_protocol.value}://{host}{base_server_path}"
        else:
            base_server_url = f"{self.session_protocol.value}://{host}:{self.session_port}{base_server_path}"
        base_server_https_url = base_server_url
        ingress_class_name = self.session_ingress_class_name
        ingress_annotations = self.session_ingress_annotations

        if ingress_class_name is None:
            ingress_class_name = ingress_annotations.get("kubernetes.io/ingress.class")

        tls_secret = (
            None if self.session_tls_secret_name is None else TlsSecret(adopt=False, name=self.session_tls_secret_name)
        )

        return (
            base_server_path,
            base_server_url,
            base_server_https_url,
            host,
            tls_secret,
            ingress_class_name,
            ingress_annotations,
        )


@dataclass(frozen=True, eq=True, kw_only=True)
class SavedClusterSettings(ClusterSettings):
    """Saved K8s Cluster settings."""

    id: ClusterId


class RuntimePlatform(StrEnum):
    """Represents a runtime platform."""

    linux_amd64 = "linux/amd64"
    linux_arm64 = "linux/arm64"


@dataclass(frozen=True, eq=True, kw_only=True)
class UnsavedResourcePool:
    """Model for a resource pool yet to be saved."""

    name: str
    classes: list[UnsavedResourceClass]
    quota: UnsavedQuota | None = None
    idle_threshold: int | None = None
    hibernation_threshold: int | None = None
    hibernation_warning_period: int | None = None
    default: bool = False
    public: bool = False
    remote: RemoteConfigurationFirecrest | None = None
    cluster_id: ClusterId | None = None
    platform: RuntimePlatform


@dataclass(frozen=True, eq=True, kw_only=True)
class ResourcePool:
    """Resource pool model."""

    name: str
    classes: list[ResourceClass]
    quota: Quota | None = None
    id: int
    idle_threshold: int | None = None
    hibernation_threshold: int | None = None
    hibernation_warning_period: int | None = None
    default: bool = False
    public: bool = False
    remote: RemoteConfigurationFirecrest | None = None
    cluster: SavedClusterSettings | None = None
    platform: RuntimePlatform

    def get_resource_class(self, resource_class_id: int) -> ResourceClass | None:
        """Find a specific resource class in the resource pool by the resource class id."""
        for rc in self.classes:
            if rc.id == resource_class_id:
                return rc
        return None

    def get_default_resource_class(self) -> ResourceClass | None:
        """Find the default resource class in the pool."""
        for rc in self.classes:
            if rc.default:
                return rc
        return None

    def get_cluster_id(self) -> ClusterId:
        """Get the ID of the cluster the resource pool refers to."""
        if self.cluster is None:
            return DEFAULT_K8S_CLUSTER
        return self.cluster.id


@dataclass(frozen=True, eq=True, kw_only=True)
class ResourcePoolPatch:
    """Model for changes requested on a resource pool."""

    name: str | None = None
    classes: list[ResourceClassPatchWithId] | None = None
    quota: QuotaPatch | ResetType | None = None
    idle_threshold: int | None | ResetType = None
    hibernation_threshold: int | None | ResetType = None
    hibernation_warning_period: int | None | ResetType = None
    default: bool | None = None
    public: bool | None = None
    remote: RemoteConfigurationPatch | None = None
    cluster_id: ClusterId | ResetType | None = None
    platform: RuntimePlatform | None = None


class RemoteConfigurationKind(StrEnum):
    """Remote resource pool kinds."""

    firecrest = "firecrest"


@dataclass(frozen=True, eq=True, kw_only=True)
class RemoteConfigurationFirecrest:
    """Model for remote configurations using the FirecREST API."""

    kind: RemoteConfigurationKind = RemoteConfigurationKind.firecrest
    provider_id: str | None = None
    api_url: str
    system_name: str
    partition: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Convert a dict object into a RemoteConfiguration instance."""
        kind = data.get("kind")
        if kind == RemoteConfigurationKind.firecrest.value:
            return cls(
                kind=RemoteConfigurationKind.firecrest,
                provider_id=data.get("provider_id") or None,
                api_url=data["api_url"],
                system_name=data["system_name"],
                partition=data.get("partition") or None,
            )
        raise errors.ValidationError(message=f"Invalid kind for remote configuration: '{kind}'")

    def to_dict(self) -> dict[str, Any]:
        """Convert this instance of RemoteConfiguration into a dictionary."""
        res = asdict(self)
        res["kind"] = self.kind.value
        return res


@dataclass(frozen=True, eq=True, kw_only=True)
class RemoteConfigurationFirecrestPatch:
    """Model for remote configurations using the FirecREST API."""

    kind: RemoteConfigurationKind | None = None
    provider_id: str | None = None
    api_url: str | None = None
    system_name: str | None = None
    partition: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert this instance of RemoteConfigurationPatch into a dictionary."""
        res = asdict(self)
        if self.kind:
            res["kind"] = self.kind.value
        return res


RemoteConfigurationPatch = ResetType | RemoteConfigurationFirecrestPatch
