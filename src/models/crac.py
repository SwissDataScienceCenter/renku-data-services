"""Domain models for the application."""
from dataclasses import asdict, dataclass, field
from typing import Callable, Optional, Protocol, Set, Union

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
        self_storage = getattr(self, "storage", None)
        if self_storage is None:
            self_storage = getattr(self, "max_storage")
        other_storage = getattr(other, "storage", None)
        if other_storage is None:
            other_storage = getattr(other, "max_storage")
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
        )

    def is_quota_valid(self, quota: "Quota") -> bool:
        """Determine if a quota is compatible with the resource class."""
        return quota > self


@dataclass(frozen=True, eq=True)
class Quota(ResourcesCompareMixin):
    """Quota model."""

    cpu: float
    memory: int
    storage: int
    gpu: int
    id: Optional[int] = None

    @classmethod
    def from_dict(cls, data: dict) -> "Quota":
        """Create the model from a plain dictionary."""
        return cls(
            cpu=data["cpu"],
            memory=data["memory"],
            storage=data["storage"],
            gpu=data["gpu"],
            id=data["id"] if "id" in data else None,
        )

    def is_resource_class_valid(self, rc: "ResourceClass") -> bool:
        """Determine if a resource class is compatible with the quota."""
        return rc <= self


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
    quota: Optional[Quota] = None
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
            if self.quota is not None and not self.quota.is_resource_class_valid(cls):
                raise ValidationError(
                    message=f"The resource class with name {cls.name} is not compatiable with the quota."
                )
            if cls.default:
                default_classes.append(cls)
        if len(default_classes) != 1:
            raise ValidationError(message="One default class is required in each resource pool.")

    def update(self, **kwargs) -> "ResourcePool":
        """Determine if an update to a resource pool is valid and if valid create new updated resource pool."""
        if self.default and "default" in kwargs and not kwargs["default"]:
            raise ValidationError(message="A default resource pool cannot be made non-default.")
        return ResourcePool.from_dict({**asdict(self), **kwargs})

    @classmethod
    def from_dict(cls, data: dict) -> "ResourcePool":
        """Create the model from a plain dictionary."""
        quota = None
        if "quota" in data and isinstance(data["quota"], dict):
            quota = Quota.from_dict(data["quota"])
        elif "quota" in data and isinstance(data["quota"], Quota):
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
