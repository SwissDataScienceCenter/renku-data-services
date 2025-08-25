"""Domain models for the application."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, Optional, Protocol
from uuid import uuid4

from renku_data_services import errors
from renku_data_services.errors import ValidationError
from renku_data_services.k8s.constants import ClusterId
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

    @classmethod
    def from_dict(cls, data: dict) -> NodeAffinity:
        """Create a node affinity from a dictionary."""
        return cls(**data)


@dataclass(frozen=True, eq=True, kw_only=True)
class ResourceClass(ResourcesCompareMixin):
    """Resource class model."""

    name: str
    cpu: float
    memory: int
    max_storage: int
    gpu: int
    id: Optional[int] = None
    default: bool = False
    default_storage: int = 1
    matching: Optional[bool] = None
    node_affinities: list[NodeAffinity] = field(default_factory=list)
    tolerations: list[str] = field(default_factory=list)
    quota: str | None = None

    def __post_init__(self) -> None:
        if len(self.name) > 40:
            raise ValidationError(message="'name' cannot be longer than 40 characters.")
        if self.default_storage > self.max_storage:
            raise ValidationError(message="The default storage cannot be larger than the max allowable storage.")
        # We need to sort node affinities and tolerations to make '__eq__' reliable
        object.__setattr__(
            self, "node_affinities", sorted(self.node_affinities, key=lambda x: (x.key, x.required_during_scheduling))
        )
        object.__setattr__(self, "tolerations", sorted(self.tolerations))

    @classmethod
    def from_dict(cls, data: dict) -> ResourceClass:
        """Create the model from a plain dictionary."""
        node_affinities: list[NodeAffinity] = []
        tolerations: list[str] = []
        quota: str | None = None
        if data.get("node_affinities"):
            node_affinities = [
                NodeAffinity.from_dict(affinity) if isinstance(affinity, dict) else affinity
                for affinity in data.get("node_affinities", [])
            ]
        if isinstance(data.get("tolerations"), list):
            tolerations = [toleration for toleration in data["tolerations"]]
        if data_quota := data.get("quota"):
            if isinstance(data_quota, str):
                quota = data_quota
            elif isinstance(data_quota, Quota):
                quota = data_quota.id
        return cls(**{**data, "tolerations": tolerations, "node_affinities": node_affinities, "quota": quota})

    def is_quota_valid(self, quota: Quota) -> bool:
        """Determine if a quota is compatible with the resource class."""
        return quota >= self

    def update(self, **kwargs: dict) -> ResourceClass:
        """Update a field of the resource class and return a new copy."""
        if not kwargs:
            return self
        return ResourceClass.from_dict({**asdict(self), **kwargs})


class GpuKind(StrEnum):
    """GPU kinds for k8s."""

    NVIDIA = "nvidia.com"
    AMD = "amd.com"


@dataclass(frozen=True, eq=True, kw_only=True)
class Quota(ResourcesCompareMixin):
    """Quota model."""

    cpu: float
    memory: int
    gpu: int
    gpu_kind: GpuKind = GpuKind.NVIDIA
    id: str

    @classmethod
    def from_dict(cls, data: dict) -> Quota:
        """Create the model from a plain dictionary."""
        instance = deepcopy(data)

        match instance.get("gpu_kind"):
            case None:
                instance["gpu_kind"] = GpuKind.NVIDIA
            case GpuKind():
                pass
            case x:
                instance["gpu_kind"] = GpuKind[x]

        match instance.get("id"):
            case None:
                instance["id"] = str(uuid4())
            case "":
                instance["id"] = str(uuid4())

        return cls(**instance)

    def is_resource_class_compatible(self, rc: ResourceClass) -> bool:
        """Determine if a resource class is compatible with the quota."""
        return rc <= self


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
    session_ingress_annotations: dict[str, Any]
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
            session_ingress_annotations=self.session_ingress_annotations,
            session_tls_secret_name=self.session_tls_secret_name,
            session_storage_class=self.session_storage_class,
            service_account_name=self.service_account_name,
        )


@dataclass(frozen=True, eq=True, kw_only=True)
class SavedClusterSettings(ClusterSettings):
    """Saved K8s Cluster settings."""

    id: ClusterId

    def get_storage_class(self) -> str | None:
        """Get the default storage class for the cluster."""

        return self.session_storage_class

    def get_ingress_parameters(self, server_name: str) -> tuple[str, str, str, str, TlsSecret | None, dict[str, str]]:
        """Returns the ingress parameters of the cluster."""

        host = self.session_host
        base_server_path = f"{self.session_path}/{server_name}"
        base_server_url = f"{self.session_protocol.value}://{host}:{self.session_port}{base_server_path}"
        base_server_https_url = base_server_url
        ingress_annotations = self.session_ingress_annotations

        tls_secret = (
            None if self.session_tls_secret_name is None else TlsSecret(adopt=False, name=self.session_tls_secret_name)
        )

        return base_server_path, base_server_url, base_server_https_url, host, tls_secret, ingress_annotations


@dataclass(frozen=True, eq=True, kw_only=True)
class ResourcePool:
    """Resource pool model."""

    name: str
    classes: list[ResourceClass]
    quota: Quota | None = None
    id: int | None = None
    idle_threshold: int | None = None
    hibernation_threshold: int | None = None
    default: bool = False
    public: bool = False
    remote: bool = False
    cluster: SavedClusterSettings | None = None

    def __post_init__(self) -> None:
        """Validate the resource pool after initialization."""
        if len(self.name) > 40:
            raise ValidationError(message="'name' cannot be longer than 40 characters.")
        if self.default and not self.public:
            raise ValidationError(message="The default resource pool has to be public.")
        if self.default and self.quota is not None:
            raise ValidationError(message="A default resource pool cannot have a quota.")
        if (self.idle_threshold and self.idle_threshold < 0) or (
            self.hibernation_threshold and self.hibernation_threshold < 0
        ):
            raise ValidationError(message="Idle threshold and hibernation threshold need to be larger than 0.")

        if self.idle_threshold == 0:
            object.__setattr__(self, "idle_threshold", None)
        if self.hibernation_threshold == 0:
            object.__setattr__(self, "hibernation_threshold", None)

        default_classes = []
        for cls in list(self.classes):
            if self.quota is not None and not self.quota.is_resource_class_compatible(cls):
                raise ValidationError(
                    message=f"The resource class with name {cls.name} is not compatible with the quota."
                )
            if cls.default:
                default_classes.append(cls)
        if len(default_classes) != 1:
            raise ValidationError(message="One default class is required in each resource pool.")

    def set_quota(self, val: Quota) -> ResourcePool:
        """Set the quota for a resource pool."""
        for cls in list(self.classes):
            if not val.is_resource_class_compatible(cls):
                raise ValidationError(
                    message=f"The resource class with name {cls.name} is not compatible with the quota."
                )
        return self.from_dict({**asdict(self), "quota": val})

    def update(self, **kwargs: Any) -> ResourcePool:
        """Determine if an update to a resource pool is valid and if valid create new updated resource pool."""
        if self.default and "default" in kwargs and not kwargs["default"]:
            raise ValidationError(message="A default resource pool cannot be made non-default.")
        return ResourcePool.from_dict({**asdict(self), **kwargs})

    @classmethod
    def from_dict(cls, data: dict) -> ResourcePool:
        """Create the model from a plain dictionary."""
        cluster: SavedClusterSettings | None = None
        quota: Quota | None = None
        classes: list[ResourceClass] = []

        if "quota" in data and isinstance(data["quota"], dict):
            quota = Quota.from_dict(data["quota"])
        elif "quota" in data and isinstance(data["quota"], Quota):
            quota = data["quota"]

        if "classes" in data and isinstance(data["classes"], set):
            classes = [ResourceClass.from_dict(c) if isinstance(c, dict) else c for c in list(data["classes"])]
        elif "classes" in data and isinstance(data["classes"], list):
            classes = [ResourceClass.from_dict(c) if isinstance(c, dict) else c for c in data["classes"]]

        match tmp := data.get("cluster"):
            case SavedClusterSettings():
                # This has to be before the dict() case, as this is also an instance of dict.
                cluster = tmp
            case dict():
                cluster = SavedClusterSettings(
                    name=tmp["name"],
                    config_name=tmp["config_name"],
                    session_protocol=tmp["session_protocol"],
                    session_host=tmp["session_host"],
                    session_port=tmp["session_port"],
                    session_path=tmp["session_path"],
                    session_ingress_annotations=tmp["session_ingress_annotations"],
                    session_tls_secret_name=tmp["session_tls_secret_name"],
                    session_storage_class=tmp["session_storage_class"],
                    id=tmp["id"],
                    service_account_name=tmp.get("service_account_name"),
                )
            case None:
                cluster = None
            case unknown:
                raise errors.ValidationError(message=f"Got unexpected cluster data {unknown} when creating model")

        return cls(
            name=data["name"],
            id=data.get("id"),
            classes=classes,
            quota=quota,
            default=data.get("default", False),
            public=data.get("public", False),
            remote=data.get("remote", False),
            idle_threshold=data.get("idle_threshold"),
            hibernation_threshold=data.get("hibernation_threshold"),
            cluster=cluster,
        )

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
