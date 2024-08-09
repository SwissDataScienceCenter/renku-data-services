"""Group models."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from ulid import ULID

from renku_data_services.authz.models import Role


@dataclass
class Group:
    """Renku group."""

    slug: str
    name: str
    created_by: str
    creation_date: datetime
    description: str | None = None
    id: ULID | None = None


@dataclass
class GroupMember:
    """Group member."""

    user_id: str
    role: Role
    group_id: str


@dataclass
class GroupMemberDetails:
    """Group member model with additional information."""

    id: str
    role: Role
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

    id: ULID
    slug: str
    kind: NamespaceKind
    created_by: str
    underlying_resource_id: ULID | str  # The user or group ID depending on the Namespace kind
    latest_slug: str | None = None
    name: str | None = None


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
