"""Domain models for the application."""
from dataclasses import dataclass
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

    async def get_user_by_id(self, id: str) -> Optional["User"]:
        """Get a user by their unique Keycloak user ID."""
        ...

    async def get_user_by_username(self, username: str) -> Optional["User"]:
        """Get a user by their username - usually this is the email in Keycloak."""
        ...


@dataclass(frozen=True, eq=True)
class User:
    """User model."""

    keycloak_id: str
    username: str
    id: Optional[int] = None

    @classmethod
    def from_dict(cls, data: dict) -> "User":
        """Create the model from a plain dictionary."""
        return cls(
            keycloak_id=data["keycloak_id"],
            username=data["username"],
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
