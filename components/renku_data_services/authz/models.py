"""Models for authorization."""

from dataclasses import dataclass
from enum import Enum

from renku_data_services.errors import errors
from renku_data_services.namespace.apispec import GroupRole


class Role(Enum):
    """Membership role."""

    OWNER: str = "owner"
    VIEWER: str = "viewer"
    EDITOR: str = "editor"

    @classmethod
    def from_group_role(cls, role: GroupRole) -> "Role":
        """Convert a group role into an authorization role."""
        match role:
            case GroupRole.owner:
                return cls.OWNER
            case GroupRole.editor:
                return cls.EDITOR
            case GroupRole.viewer:
                return cls.VIEWER
            case _:
                raise errors.ProgrammingError(message=f"Could not convert group role {role} into a role")

    def to_group_role(self) -> GroupRole:
        """Convert a group role into an authorization role."""
        match self:
            case self.OWNER:
                return GroupRole.owner
            case self.EDITOR:
                return GroupRole.editor
            case self.VIEWER:
                return GroupRole.viewer
            case _:
                raise errors.ProgrammingError(message=f"Could not convert role {self} into a group role")


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
