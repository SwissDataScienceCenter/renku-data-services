"""Domain models for the application."""
from dataclasses import dataclass, field
from typing import Optional, Protocol, Set


@dataclass(frozen=True, eq=True)
class ResourceClass:
    """Resource class model."""

    name: str
    cpu: float
    memory: int
    storage: int
    gpu: int
    id: Optional[int] = None

    @classmethod
    def from_dict(cls, data: dict) -> "ResourceClass":
        """Create the model from a plain dictionary."""
        return cls(
            cpu=data["cpu"],
            memory=data["memory"],
            storage=data["storage"],
            gpu=data["gpu"],
            name=data["name"],
            id=data["id"] if "id" in data else None,
        )


@dataclass(frozen=True, eq=True)
class Quota:
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

    @classmethod
    def from_dict(cls, data: dict) -> "ResourcePool":
        """Create the model from a plain dictionary."""
        return cls(
            name=data["name"],
            classes={ResourceClass(**c) for c in data["classes"]},
            quota=Quota(**data["quota"]) if "quota" in data else None,
            id=data["id"] if "id" in data else None,
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
