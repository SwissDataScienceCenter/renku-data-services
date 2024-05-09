"""Group models."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from renku_data_services import errors


@dataclass
class Group:
    """Renku group."""

    slug: str
    name: str
    created_by: str
    creation_date: datetime
    description: str | None = None
    id: str | None = None


class GroupRole(int, Enum):
    """Role for a group member."""

    owner: int = 80
    member: int = 40

    @classmethod
    def from_str(cls, val: str):
        """Get an enum from a string value, the provided value is checked in case-insensitive way."""
        match val.lower():
            case "owner":
                return cls(80)
            case "member":
                return cls(40)
            case _:
                errors.ValidationError(message=f"The value {val} is not a valid group member role")


@dataclass
class GroupMember:
    """Group member."""

    user_id: str
    role: GroupRole
    group_id: str


@dataclass
class GroupMemberDetails:
    """Group member model with additional information."""

    id: str
    role: GroupRole
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None


class NamespaceKind(str, Enum):
    """Allowed kinds of namespaces."""

    group: str = "group"
    user: str = "user"


@dataclass
class Namespace:
    """A renku namespace."""

    id: str
    slug: str
    kind: NamespaceKind
    name: str | None = None
    creation_date: datetime | None = None
    created_by: str | None = None
    latest_slug: str | None = None


@dataclass
class GroupUpdate:
    """Information about the update of a group."""

    old: Group
    new: Group


@dataclass
class NamespaceUpdate:
    """Information about the update of a namespace."""

    old: Namespace
    new: Namespace
