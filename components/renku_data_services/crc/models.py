"""Domain models for the application."""

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, Optional, Protocol
from uuid import uuid4

from renku_data_services.errors import ValidationError


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
        """Maximum allowable storeage in gigabytes."""
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
    def from_dict(cls, data: dict) -> "NodeAffinity":
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
    def from_dict(cls, data: dict) -> "ResourceClass":
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

    def is_quota_valid(self, quota: "Quota") -> bool:
        """Determine if a quota is compatible with the resource class."""
        return quota >= self

    def update(self, **kwargs: dict) -> "ResourceClass":
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
    id: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict) -> "Quota":
        """Create the model from a plain dictionary."""
        gpu_kind = GpuKind.NVIDIA
        if "gpu_kind" in data:
            gpu_kind = data["gpu_kind"] if isinstance(data["gpu_kind"], GpuKind) else GpuKind[data["gpu_kind"]]
        return cls(**{**data, "gpu_kind": gpu_kind})

    def is_resource_class_compatible(self, rc: "ResourceClass") -> bool:
        """Determine if a resource class is compatible with the quota."""
        return rc <= self

    def generate_id(self) -> "Quota":
        """Create a new quota with its ID set to a uuid."""
        if self.id is not None:
            return self
        return self.from_dict({**asdict(self), "id": str(uuid4())})


@dataclass(frozen=True, eq=True, kw_only=True)
class KubeClusterSettings:
    """K8s Cluster settings."""

    config_name: str
    node_affinities: list[str]
    tolerations: list[str]


@dataclass(frozen=True, eq=True, kw_only=True)
class ResourcePool:
    """Resource pool model."""

    name: str
    classes: list["ResourceClass"]
    quota: Optional[Quota] = None
    id: Optional[int] = None
    idle_threshold: Optional[int] = None
    hibernation_threshold: Optional[int] = None
    default: bool = False
    public: bool = False
    cluster: Optional[KubeClusterSettings] = None

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
            if self.quota and not self.quota.is_resource_class_compatible(cls):
                raise ValidationError(
                    message=f"The resource class with name {cls.name} is not compatible with the quota."
                )
            if cls.default:
                default_classes.append(cls)
        if len(default_classes) != 1:
            raise ValidationError(message="One default class is required in each resource pool.")

    def set_quota(self, val: Quota) -> "ResourcePool":
        """Set the quota for a resource pool."""
        for cls in list(self.classes):
            if not val.is_resource_class_compatible(cls):
                raise ValidationError(
                    message=f"The resource class with name {cls.name} is not compatiable with the quota."
                )
        return self.from_dict({**asdict(self), "quota": val})

    def update(self, **kwargs: Any) -> "ResourcePool":
        """Determine if an update to a resource pool is valid and if valid create new updated resource pool."""
        if self.default and "default" in kwargs and not kwargs["default"]:
            raise ValidationError(message="A default resource pool cannot be made non-default.")
        return ResourcePool.from_dict({**asdict(self), **kwargs})

    @classmethod
    def from_dict(cls, data: dict) -> "ResourcePool":
        """Create the model from a plain dictionary."""
        quota: Optional[Quota] = None
        if "quota" in data and isinstance(data["quota"], dict):
            quota = Quota.from_dict(data["quota"])
        elif "quota" in data and isinstance(data["quota"], Quota):
            quota = data["quota"]
        if "classes" in data and isinstance(data["classes"], set):
            classes = [ResourceClass.from_dict(c) if isinstance(c, dict) else c for c in list(data["classes"])]
        elif "classes" in data and isinstance(data["classes"], list):
            classes = [ResourceClass.from_dict(c) if isinstance(c, dict) else c for c in data["classes"]]
        return cls(
            name=data["name"],
            id=data.get("id"),
            classes=classes,
            quota=quota,
            default=data.get("default", False),
            public=data.get("public", False),
            idle_threshold=data.get("idle_threshold"),
            hibernation_threshold=data.get("hibernation_threshold"),
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
