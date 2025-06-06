"""Base models shared by services."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, StrEnum
from typing import ClassVar, Final, Never, NewType, Optional, Protocol, Self, TypeVar, overload

from sanic import Request

from renku_data_services.errors import errors


@dataclass(kw_only=True, frozen=True)
class APIUser:
    """The model for a user of the API, used for authentication."""

    id: str | None = None  # the sub claim in the access token - i.e. the Keycloak user ID
    access_token: str | None = field(repr=False, default=None)
    refresh_token: str | None = field(repr=False, default=None)
    full_name: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    access_token_expires_at: datetime | None = None
    is_admin: bool = False

    @property
    def is_authenticated(self) -> bool:
        """Indicates whether the user has successfully logged in."""
        return self.id is not None

    @property
    def is_anonymous(self) -> bool:
        """Indicates whether the user is anonymous."""
        return isinstance(self, AnonymousAPIUser)

    def get_full_name(self) -> str | None:
        """Generate the closest thing to a full name if the full name field is not set."""
        full_name = self.full_name or " ".join(filter(None, (self.first_name, self.last_name)))
        if len(full_name) == 0:
            return None
        return full_name


@dataclass(kw_only=True, frozen=True)
class AuthenticatedAPIUser(APIUser):
    """The model for a an authenticated user of the API."""

    id: str
    email: str
    access_token: str = field(repr=False)
    refresh_token: str | None = field(default=None, repr=False)
    full_name: str | None = None
    first_name: str | None = None
    last_name: str | None = None


@dataclass(kw_only=True, frozen=True)
class AnonymousAPIUser(APIUser):
    """The model for an anonymous user of the API."""

    id: str
    is_admin: bool = field(init=False, default=False)

    @property
    def is_authenticated(self) -> bool:
        """We cannot authenticate anonymous users, so this is by definition False."""
        return False


class ServiceAdminId(StrEnum):
    """Types of internal service admins."""

    migrations = "migrations"
    secrets_rotation = "secrets_rotation"
    k8s_watcher = "k8s_watcher"


@dataclass(kw_only=True, frozen=True)
class InternalServiceAdmin(APIUser):
    """Used to gain complete admin access by internal code components when performing tasks not started by users."""

    id: ServiceAdminId = ServiceAdminId.migrations
    access_token: str = field(repr=False, default="internal-service-admin", init=False)
    full_name: str | None = field(default=None, init=False)
    first_name: str | None = field(default=None, init=False)
    last_name: str | None = field(default=None, init=False)
    email: str | None = field(default=None, init=False)
    is_admin: bool = field(init=False, default=True)

    @property
    def is_authenticated(self) -> bool:
        """Internal admin users are always authenticated."""
        return True


class GitlabAccessLevel(Enum):
    """Gitlab access level for filtering projects."""

    PUBLIC = 1
    """User isn't a member but project is public"""
    MEMBER = 2
    """User is a member of the project"""
    ADMIN = 3
    """A user with at least DEVELOPER priviledges in gitlab is considered an Admin"""


class GitlabAPIProtocol(Protocol):
    """The interface for interacting with the Gitlab API."""

    async def filter_projects_by_access_level(
        self, user: APIUser, project_ids: list[str], min_access_level: GitlabAccessLevel
    ) -> list[str]:
        """Get a list of projects of which the user is a member with a specific access level."""
        ...


class UserStore(Protocol):
    """The interface through which Keycloak or a similar application can be accessed."""

    async def get_user_by_id(self, id: str, access_token: str) -> Optional[User]:
        """Get a user by their unique Keycloak user ID."""
        ...


@dataclass(frozen=True, eq=True, kw_only=True)
class User:
    """User model."""

    keycloak_id: str
    id: Optional[int] = None
    no_default_access: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> User:
        """Create the model from a plain dictionary."""
        return cls(**data)


@dataclass(frozen=True, eq=True)
class Slug:
    """Slug used for namespaces, groups, projects, etc."""

    value: str
    # Slug regex rules
    # from https://docs.gitlab.com/ee/user/reserved_names.html#limitations-on-usernames-project-and-group-names
    # - cannot end in .git
    # - cannot end in .atom
    # - cannot contain any combination of two or more consecutive -._
    # - has to start with letter or number
    _regex: ClassVar[str] = r"^(?!.*\.git$|.*\.atom$|.*[\-._][\-._].*)[a-zA-Z0-9][a-zA-Z0-9\-_.]*$"

    def __init__(self, value: str) -> None:
        if not re.match(self._regex, value):
            raise errors.ValidationError(message=f"The slug {value} does not match the regex {self._regex}")
        object.__setattr__(self, "value", value)

    @classmethod
    def from_name(cls, name: str) -> Self:
        """Takes a name with any amount of invalid characters and transforms it in a valid slug."""
        lower_case = name.lower()
        no_space = re.sub(r"\s+", "-", lower_case)
        normalized = unicodedata.normalize("NFKD", no_space).encode("ascii", "ignore").decode("utf-8")
        valid_chars_pattern = [r"\w", ".", "_", "-"]
        no_invalid_characters = re.sub(f"[^{''.join(valid_chars_pattern)}]", "-", normalized)
        no_duplicates = re.sub(r"([._-])[._-]+", r"\1", no_invalid_characters)
        valid_start = re.sub(r"^[._-]", "", no_duplicates)
        valid_end = re.sub(r"[._-]$", "", valid_start)
        no_dot_git_or_dot_atom_at_end = re.sub(r"(\.atom|\.git)+$", "", valid_end)
        if len(no_dot_git_or_dot_atom_at_end) == 0:
            raise errors.ValidationError(
                message="The name for the project contains too many invalid characters so a slug could not be generated"
            )
        return cls(no_dot_git_or_dot_atom_at_end)

    @classmethod
    def from_user(cls, email: str | None, first_name: str | None, last_name: str | None, keycloak_id: str) -> Self:
        """Create a slug from a user."""
        if email:
            slug = email.split("@")[0]
        elif first_name and last_name:
            slug = first_name + "-" + last_name
        elif last_name:
            slug = last_name
        elif first_name:
            slug = first_name
        else:
            slug = "user_" + keycloak_id
        # The length limit is 99 but leave some space for modifications that may be added down the line
        # to filter out invalid characters or to generate a unique name
        slug = slug[:80]
        return cls.from_name(slug)

    def __str__(self) -> str:
        return self.value

    def __repr__(self) -> str:
        return self.value


class NamespaceSlug(Slug):
    """The slug for a group or user namespace."""


class GlobalNamespaceSlug(NamespaceSlug):
    """The slug for the global namespace."""

    def __init__(self) -> None:
        object.__setattr__(self, "value", GLOBAL_NAMESPACE_SLUG_STR)


class ProjectSlug(Slug):
    """The slug for a project."""


class DataConnectorSlug(Slug):
    """The slug for a data connector."""


class __NamespaceCommonMixin:
    def __repr__(self) -> str:
        return "/".join([i.value for i in self.to_list()])

    def __getitem__(self, ind: int) -> Slug:
        return self.to_list()[ind]

    def __len__(self) -> int:
        return len(self.to_list())

    def to_list(self) -> list[Slug]:
        raise NotImplementedError

    def serialize(self) -> str:
        return "/".join([i.value for i in self.to_list()])


@dataclass(frozen=True, eq=True, repr=False)
class NamespacePath(__NamespaceCommonMixin):
    """The slug that makes up the path to a user or group namespace in Renku."""

    __match_args__ = ("first",)
    first: NamespaceSlug

    @overload
    def __truediv__(self, other: ProjectSlug) -> ProjectPath: ...
    @overload
    def __truediv__(self, other: DataConnectorSlug) -> DataConnectorPath: ...

    def __truediv__(self, other: ProjectSlug | DataConnectorSlug) -> ProjectPath | DataConnectorPath:
        """Create new entity path with an extra slug."""
        if isinstance(other, ProjectSlug):
            return ProjectPath(self.first, other)
        elif isinstance(other, DataConnectorSlug):
            return DataConnectorPath(self.first, other)
        else:
            raise errors.ProgrammingError(message=f"A path for a namespace cannot be further joined with {other}")

    def to_list(self) -> list[Slug]:
        """Convert to list of slugs."""
        return [self.first]

    def parent(self) -> Never:
        """The parent path."""
        raise errors.ProgrammingError(message="A namespace path has no parent")

    def last(self) -> NamespaceSlug:
        """Return the last slug in the path."""
        return self.first

    @classmethod
    def from_strings(cls, *slugs: str) -> Self:
        """Convert a string to a namespace path."""
        if len(slugs) != 1:
            raise errors.ValidationError(message=f"One slug string is needed to create a namespace path, got {slugs}.")
        return cls(NamespaceSlug(slugs[0]))


@dataclass(frozen=True, eq=True, repr=False)
class ProjectPath(__NamespaceCommonMixin):
    """The collection of slugs that makes up the path to a project in Renku."""

    __match_args__ = ("first", "second")
    first: NamespaceSlug
    second: ProjectSlug

    def __truediv__(self, other: DataConnectorSlug) -> DataConnectorInProjectPath:
        """Create new entity path with an extra slug."""
        if not isinstance(other, DataConnectorSlug):
            raise errors.ValidationError(
                message=f"A project path can only be joined with a data connector slug, but got {other}"
            )
        return DataConnectorInProjectPath(self.first, self.second, other)

    def to_list(self) -> list[Slug]:
        """Convert to list of slugs."""
        return [self.first, self.second]

    def parent(self) -> NamespacePath:
        """The parent path."""
        return NamespacePath(self.first)

    def last(self) -> ProjectSlug:
        """Return the last slug in the path."""
        return self.second

    @classmethod
    def from_strings(cls, *slugs: str) -> Self:
        """Convert strings to a project path."""
        if len(slugs) != 2:
            raise errors.ValidationError(message=f"Two slug strings are needed to create a project path, got {slugs}.")
        return cls(NamespaceSlug(slugs[0]), ProjectSlug(slugs[1]))


@dataclass(frozen=True, eq=True, repr=False)
class DataConnectorPath(__NamespaceCommonMixin):
    """The collection of slugs that makes up the path to a data connector in a user or group in Renku."""

    __match_args__ = ("first", "second")
    first: NamespaceSlug
    second: DataConnectorSlug

    def __truediv__(self, other: Never) -> Never:
        """Create new entity path with an extra slug."""
        raise errors.ProgrammingError(
            message="A path for a data connector in a user or group cannot be further joined with more slugs"
        )

    def to_list(self) -> list[Slug]:
        """Convert to list of slugs."""
        return [self.first, self.second]

    def parent(self) -> NamespacePath:
        """The parent path."""
        return NamespacePath(self.first)

    def last(self) -> DataConnectorSlug:
        """Return the last slug in the path."""
        return self.second

    @classmethod
    def from_strings(cls, *slugs: str) -> Self:
        """Convert strings to a data connector path."""
        if len(slugs) != 2:
            raise errors.ValidationError(
                message=f"Two slug strings are needed to create a data connector path, got {slugs}."
            )
        return cls(NamespaceSlug(slugs[0]), DataConnectorSlug(slugs[1]))


@dataclass(frozen=True, eq=True, repr=False)
class DataConnectorInProjectPath(__NamespaceCommonMixin):
    """The collection of slugs that makes up the path to a data connector in a projectj in Renku."""

    __match_args__ = ("first", "second", "third")
    first: NamespaceSlug
    second: ProjectSlug
    third: DataConnectorSlug

    def __truediv__(self, other: Never) -> Never:
        """Create new entity path with an extra slug."""
        raise errors.ProgrammingError(
            message="A path for a data connector in a project cannot be further joined with more slugs"
        )

    def to_list(self) -> list[Slug]:
        """Convert to list of slugs."""
        return [self.first, self.second, self.third]

    def parent(self) -> ProjectPath:
        """The parent path."""
        return ProjectPath(self.first, self.second)

    def last(self) -> DataConnectorSlug:
        """Return the last slug in the path."""
        return self.third

    @classmethod
    def from_strings(cls, *slugs: str) -> Self:
        """Convert strings to a data connector path."""
        if len(slugs) != 3:
            raise errors.ValidationError(
                message=f"Three slug strings are needed to create a data connector in project path, got {slugs}."
            )
        return cls(NamespaceSlug(slugs[0]), ProjectSlug(slugs[1]), DataConnectorSlug(slugs[2]))


GLOBAL_NAMESPACE_SLUG_STR: Final[str] = "_global"
"""The string value of the slug of the global namespace."""
GLOBAL_NAMESPACE_SLUG: Final[GlobalNamespaceSlug] = GlobalNamespaceSlug()
"""The value of the slug of the global namespace."""
GLOBAL_NAMESPACE_PATH: Final[NamespacePath] = NamespacePath(first=GLOBAL_NAMESPACE_SLUG)
"""The value of the path of the global namespace."""

AnyAPIUser = TypeVar("AnyAPIUser", bound=APIUser, covariant=True)


class Authenticator(Protocol[AnyAPIUser]):
    """Interface for authenticating users."""

    token_field: str

    async def authenticate(self, access_token: str, request: Request) -> AnyAPIUser:
        """Validates the user credentials (i.e. we can say that the user is a valid Renku user)."""
        ...


ResetType = NewType("ResetType", object)
"""This type represents that a value that may be None should be reset back to None or null.
This type should have only one instance, defined in the same file as this type.
"""

RESET: ResetType = ResetType(object())
"""The single instance of the ResetType, can be compared to similar to None, i.e. `if value is RESET`"""


class ResourceType(StrEnum):
    """All possible resources stored in Authzed."""

    project = "project"
    user = "user"
    anonymous_user = "anonymous_user"
    platform = "platform"
    group = "group"
    user_namespace = "user_namespace"
    data_connector = "data_connector"
