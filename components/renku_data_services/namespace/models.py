"""Group models."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Final

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

    def __truediv__(self, other: "Namespace") -> "NamespacePath":
        return NamespacePath(self, other)


class NamespacePath:
    """A list of namespaces that are hierarchical."""

    def __init__(self, *args: Namespace) -> None:
        if len(args) < 1:
            raise errors.ValidationError(message="A NamespacePath has to be initialized with at least 1 namespace .")
        if len(args) > 2:
            raise errors.ValidationError(message="A NamespacePath has to be initialized with at most 2 namespaces .")
        if len(args) >= 2 and args[0].kind not in [NamespaceKind.group, NamespaceKind.user]:
            raise errors.ValidationError(
                message="A NamespacePath with more than 1 segment has to have a user or group"
                f" namespace in the first position, instead there is {args[0].kind}."
            )
        self.__value: list[Namespace] = list(args)

    def __getitem__(self, ind: int) -> Namespace:
        return self.__value[ind]

    def __len__(self) -> int:
        return len(self.__value)

    def __truediv__(self, other: Namespace) -> "NamespacePath":
        return NamespacePath(*self.__value, other)

    @property
    def path(self) -> str:
        """Join the latest slugs of each namespace with /."""
        return "/".join([i.latest_slug or i.slug for i in self.__value])

    @property
    def last(self) -> Namespace:
        """Return the last namespace in the path."""
        return self.__value[-1]

    def __eq__(self, other: Any, /) -> bool:
        if not isinstance(other, type(self)):
            return False
        if len(self) != len(other):
            return False
        return all([ns == other[i] for i, ns in enumerate(self.__value)])

    def __ne__(self, other: Any, /) -> bool:
        return not (self == other)

    def __repr__(self) -> str:
        namespaces = ", ".join([str(i) for i in self.__value])
        return f"NamespacePath({namespaces})"

    def to_list(self) -> list[Namespace]:
        """Return a copy of the list of namespaces."""
        return [i for i in self.__value]


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
