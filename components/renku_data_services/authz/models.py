"""Models for authorization."""

from dataclasses import dataclass
from enum import Enum


class Role(Enum):
    """Membership role."""

    OWNER: str = "owner"
    VIEWER: str = "viewer"
    EDITOR: str = "editor"


class Scope(Enum):
    """Types of permissions - i.e. scope."""

    READ: str = "read"
    WRITE: str = "write"
    DELETE: str = "delete"
    CHANGE_MEMBERSHIP: str = "change_membership"


@dataclass
class Member:
    """A class to hold a user and her role."""

    role: Role
    user_id: str
    resource_id: str


class Change(Enum):
    """The type of change executed on a specific resource."""

    UPDATE: str = "update"
    ADD: str = "add"
    REMOVE: str = "remove"


@dataclass
class MembershipChange:
    """The change of a member of a resource in the authorization service."""

    member: Member
    change: Change


class Visibility(Enum):
    """The visisibilty of a resource."""

    PUBLIC: str = "public"
    PRIVATE: str = "private"
