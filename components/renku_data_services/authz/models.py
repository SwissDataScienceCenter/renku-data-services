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


class Visibility(Enum):
    """The visisibilty of a resource."""

    PUBLIC: str = "public"
    PRIVATE: str = "private"
