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


class GroupRole(Enum):
    """Role for a group member."""

    OWNER: int = 80
    MEMBER: int = 40

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
