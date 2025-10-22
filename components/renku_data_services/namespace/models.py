"""Group models."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Final

from ulid import ULID

from renku_data_services.authz.models import Role
from renku_data_services.base_models.core import NamespacePath, ProjectPath, ResourceType
from renku_data_services.errors import errors


@dataclass(kw_only=True)
class UnsavedGroup:
    """Renku group."""

    slug: str
    name: str
    description: str | None = None

    @property
    def path(self) -> NamespacePath:
        """Return the path of this group."""
        return NamespacePath.from_strings(self.slug)


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


class NamespaceKind(StrEnum):
    """Allowed kinds of namespaces."""

    group = "group"
    user = "user"
    project = "project"  # For now only applicable to data connectors

    def to_resource_type(self) -> ResourceType:
        """Conver the namespace kind to the corresponding resource type."""
        if self == NamespaceKind.group:
            return ResourceType.group
        elif self == NamespaceKind.user:
            return ResourceType.user_namespace
        elif self == NamespaceKind.project:
            return ResourceType.project
        raise errors.ProgrammingError(message=f"Unhandled namespace kind {self}")


@dataclass(frozen=True, kw_only=True)
class Namespace:
    """A renku namespace."""

    id: ULID
    kind: NamespaceKind
    created_by: str
    path: NamespacePath | ProjectPath
    underlying_resource_id: ULID | str  # The user, group or project ID depending on the Namespace kind
    latest_slug: str | None = None
    name: str | None = None
    creation_date: datetime | None = None


@dataclass(frozen=True, kw_only=True)
class UserNamespace(Namespace):
    """A renku user namespace."""

    path: NamespacePath
    underlying_resource_id: str  # This corresponds to the keycloak user ID - which is not a ULID
    kind: Final[NamespaceKind] = field(default=NamespaceKind.user, init=False)


@dataclass(frozen=True, kw_only=True)
class GroupNamespace(Namespace):
    """A renku group namespace."""

    path: NamespacePath
    underlying_resource_id: ULID
    kind: Final[NamespaceKind] = field(default=NamespaceKind.group, init=False)


@dataclass(frozen=True, kw_only=True)
class ProjectNamespace(Namespace):
    """A renku project namespace."""

    path: ProjectPath
    underlying_resource_id: ULID
    kind: Final[NamespaceKind] = field(default=NamespaceKind.project, init=False)


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
class GroupPermissions:
    """The permissions of a user on a given group."""

    write: bool
    delete: bool
    change_membership: bool
