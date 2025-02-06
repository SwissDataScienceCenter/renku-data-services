"""Group models."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from ulid import ULID

from renku_data_services.authz.models import Role


@dataclass(kw_only=True)
class UnsavedGroup:
    """Renku group."""

    slug: str
    name: str
    description: str | None = None


@dataclass(kw_only=True)
class Group(UnsavedGroup):
    """Renku group stored in the database."""

    created_by: str
    creation_date: datetime

    id: ULID


@dataclass
class DeletedGroup:
    """A group that was deleted from the DB."""

    id: ULID


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
    namespace: str | None = None
    first_name: str | None = None
    last_name: str | None = None


class NamespaceKind(str, Enum):
    """Allowed kinds of namespaces."""

    group = "group"
    user = "user"
    project = "project"  # For now only applicable to data connectors


@dataclass
class Namespace:
    """A renku namespace."""

    id: ULID
    slug: str
    kind: NamespaceKind
    created_by: str
    underlying_resource_id: ULID | str  # The user, group or project ID depending on the Namespace kind
    latest_slug: str | None = None
    name: str | None = None
    creation_date: datetime | None = None


@dataclass(frozen=True, eq=True, kw_only=True)
class GroupPatch:
    """Model for changes requested on a group."""

    slug: str | None
    name: str | None
    description: str | None


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


@dataclass
class GroupPermissions:
    """The permissions of a user on a given group."""

    write: bool
    delete: bool
    change_membership: bool
