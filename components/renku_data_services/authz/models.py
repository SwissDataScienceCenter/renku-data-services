"""Models for projects."""
from enum import Enum


class AccessLevel(Enum):
    """
    Project access level.

    Higher values have more access than lower values and
    all higher values include the permissions from lower access levels.
    For example an owner (value 80) is also a member (values 40) and has
    public access permissions (value 0) on the project.
    """

    PUBLIC_ACCESS: int = 0
    MEMBER: int = 40
    OWNER: int = 80


class PermissionQualifier(Enum):
    """Used to express additional intent or details about permission decisions."""

    ALL: str = "all"
    SOME: str = "some"
    NONE: str = "none"
