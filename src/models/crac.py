"""Domain models for the application."""
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Callable, Optional, Protocol, Set, Union
from uuid import uuid4

from models.errors import ValidationError


class ResourcesCompareMixin:
    """A mixin that adds comparison operator support on ResourceClasses and Quotas."""

    def __compare(
        self,
        other: Union["Quota", "ResourceClass"],
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

    def __ge__(self, other: Union["Quota", "ResourceClass"]):
        return self.__compare(other, lambda x, y: x >= y)

    def __gt__(self, other: Union["Quota", "ResourceClass"]):
        return self.__compare(other, lambda x, y: x > y)

    def __lt__(self, other: Union["Quota", "ResourceClass"]):
        return self.__compare(other, lambda x, y: x < y)

    def __le__(self, other: Union["Quota", "ResourceClass"]):
        return self.__compare(other, lambda x, y: x <= y)


@dataclass(frozen=True, eq=True)
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

    def __post_init__(self):
        if self.default_storage > self.max_storage:
            raise ValidationError(message="The default storage cannot be larger than the max allowable storage.")

    @classmethod
    def from_dict(cls, data: dict) -> "ResourceClass":
        """Create the model from a plain dictionary."""
        return cls(
            cpu=data["cpu"],
            memory=data["memory"],
            max_storage=data["max_storage"],
            gpu=data["gpu"],
            name=data["name"],
            id=data["id"] if "id" in data else None,
            default=data["default"] if "default" in data else False,
            default_storage=data["default_storage"] if "default" in data else 1,
        )

    def is_quota_valid(self, quota: "Quota") -> bool:
        """Determine if a quota is compatible with the resource class."""
        return quota >= self


class GpuKind(StrEnum):
    """GPU kinds for k8s."""

    NVIDIA = "nvidia.com"
    AMD = "amd.com"


@dataclass(frozen=True, eq=True)
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
        if "gpu_kind" in data:
            data["gpu_kind"] = data["gpu_kind"] if isinstance(data["gpu_kind"], GpuKind) else GpuKind[data["gpu_kind"]]
        return cls(**data)

    def is_resource_class_valid(self, rc: "ResourceClass") -> bool:
        """Determine if a resource class is compatible with the quota."""
        return rc <= self

    def generate_id(self) -> "Quota":
        """Create a new quota with its ID set to a uuid."""
        if self.id is not None:
            return self
        return self.from_dict({**asdict(self), "id": str(uuid4())})


class UserStore(Protocol):
    """The interface through which Keycloak or a similar application can be accessed."""

    async def get_user_by_id(self, id: str, access_token: str) -> Optional["User"]:
        """Get a user by their unique Keycloak user ID."""
        ...


class Authenticator(Protocol):
    """Interface for authenticating users."""

    async def authenticate(self, access_token: str) -> "APIUser":
        """Validates the user credentials (i.e. we can say that the user is a valid Renku user)."""
        ...


@dataclass(frozen=True, eq=True)
class User:
    """User model."""

    keycloak_id: str
    id: Optional[int] = None

    @classmethod
    def from_dict(cls, data: dict) -> "User":
        """Create the model from a plain dictionary."""
        return cls(
            keycloak_id=data["keycloak_id"],
            id=data["id"] if "id" in data else None,
        )


@dataclass(frozen=True, eq=True)
class ResourcePool:
    """Resource pool model."""

    name: str
    classes: Set["ResourceClass"]
    quota: Optional[Quota | str] = None
    id: Optional[int] = None
    default: bool = False
    public: bool = False

    def __post_init__(self):
        """Validate the resource pool after initialization."""
        if self.default and not self.public:
            raise ValidationError(message="The default resource pool has to be public.")
        if self.default and self.quota is not None:
            raise ValidationError(message="A default resource pool cannot have a quota.")
        default_classes = []
        for cls in list(self.classes):
            if isinstance(self.quota, Quota) and not self.quota.is_resource_class_valid(cls):
                raise ValidationError(
                    message=f"The resource class with name {cls.name} is not compatiable with the quota."
                )
            if cls.default:
                default_classes.append(cls)
        if len(default_classes) != 1:
            raise ValidationError(message="One default class is required in each resource pool.")

    def set_quota(self, val: Optional[Quota | str]) -> "ResourcePool":
        """Set the quota for a resource pool."""
        for cls in list(self.classes):
            if isinstance(val, Quota) and not val.is_resource_class_valid(cls):
                raise ValidationError(
                    message=f"The resource class with name {cls.name} is not compatiable with the quota."
                )
        return self.from_dict({**asdict(self), "quota": val})

    def update(self, **kwargs) -> "ResourcePool":
        """Determine if an update to a resource pool is valid and if valid create new updated resource pool."""
        if self.default and "default" in kwargs and not kwargs["default"]:
            raise ValidationError(message="A default resource pool cannot be made non-default.")
        return ResourcePool.from_dict({**asdict(self), **kwargs})

    @classmethod
    def from_dict(cls, data: dict) -> "ResourcePool":
        """Create the model from a plain dictionary."""
        quota: Optional[str | Quota] = None
        if "quota" in data and isinstance(data["quota"], dict):
            quota = Quota.from_dict(data["quota"])
        elif "quota" in data and (isinstance(data["quota"], Quota) or isinstance(data["quota"], str)):
            quota = data["quota"]
        classes = set()
        if "classes" in data and isinstance(data["classes"], set):
            classes = {ResourceClass.from_dict(c) if isinstance(c, dict) else c for c in list(data["classes"])}
        elif "classes" in data and isinstance(data["classes"], list):
            classes = {ResourceClass.from_dict(c) if isinstance(c, dict) else c for c in data["classes"]}
        return cls(
            name=data["name"],
            id=data["id"] if "id" in data else None,
            classes=classes,
            quota=quota,
            default=data["default"] if "default" in data else False,
            public=data["public"] if "public" in data else False,
        )


@dataclass
class APIUser:
    """The model for a user of the API, used for authentication."""

    is_admin: bool = False
    id: Optional[str] = None
    access_token: Optional[str] = field(repr=False, default=None)

    @property
    def is_authenticated(self):
        """Indicates whether the user has sucessfully logged in."""
        return self.id is not None
