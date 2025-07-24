"""Models for authorization."""

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from ulid import ULID

from renku_data_services.errors import errors
from renku_data_services.namespace.apispec import GroupRole

if TYPE_CHECKING:
    from renku_data_services.base_models.core import ResourceType


class Role(Enum):
    """Membership role."""

    OWNER = "owner"
    VIEWER = "viewer"
    EDITOR = "editor"

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
            case Role.OWNER:
                return GroupRole.owner
            case Role.EDITOR:
                return GroupRole.editor
            case Role.VIEWER:
                return GroupRole.viewer
            case _:
                raise errors.ProgrammingError(message=f"Could not convert role {self} into a group role")


class Scope(Enum):
    """Types of permissions - i.e. scope."""

    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    CHANGE_MEMBERSHIP = "change_membership"
    READ_CHILDREN = "read_children"
    ADD_LINK = "add_link"
    IS_ADMIN = "is_admin"
    NON_PUBLIC_READ = "non_public_read"
    EXCLUSIVE_MEMBER = "exclusive_member"
    EXCLUSIVE_EDITOR = "exclusive_editor"
    EXCLUSIVE_OWNER = "exclusive_owner"
    DIRECT_MEMBER = "direct_member"


@dataclass
class UnsavedMember:
    """A class to hold a user and her role."""

    role: Role
    user_id: str

    def with_group(self, group_id: ULID) -> "Member":
        """Turn to member with group."""
        return Member(role=self.role, user_id=self.user_id, resource_id=group_id)


@dataclass
class Member(UnsavedMember):
    """Member stored in the database."""

    resource_id: ULID


class Change(Enum):
    """The type of change executed on a specific resource."""

    UPDATE = "update"
    ADD = "add"
    REMOVE = "remove"


@dataclass
class MembershipChange:
    """The change of a member of a resource in the authorization service."""

    member: Member
    change: Change


class Visibility(Enum):
    """The visibility of a resource."""

    PUBLIC = "public"
    PRIVATE = "private"


@dataclass
class CheckPermissionItem:
    """Represent a permission item to be checked by the authorization service."""

    resource_type: "ResourceType"
    resource_id: str | ULID
    scope: Scope
