"""Base models shared by services."""

import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from typing import ClassVar, Optional, Protocol

from sanic import Request

from renku_data_services.errors import errors


class Authenticator(Protocol):
    """Interface for authenticating users."""

    token_field: str

    async def authenticate(self, access_token: str, request: Request) -> "APIUser":
        """Validates the user credentials (i.e. we can say that the user is a valid Renku user)."""
        ...


@dataclass(kw_only=True)
class APIUser:
    """The model for a user of the API, used for authentication."""

    is_admin: bool = False
    id: Optional[str] = None  # the sub claim in the access token - i.e. the Keycloak user ID
    access_token: Optional[str] = field(repr=False, default=None)
    full_name: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None

    @property
    def is_authenticated(self) -> bool:
        """Indicates whether the user has successfully logged in."""
        return self.id is not None


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

    async def get_user_by_id(self, id: str, access_token: str) -> Optional["User"]:
        """Get a user by their unique Keycloak user ID."""
        ...


@dataclass(frozen=True, eq=True, kw_only=True)
class User:
    """User model."""

    keycloak_id: str
    id: Optional[int] = None
    no_default_access: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> "User":
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
    _regex: ClassVar[str] = "^(?!.*\\.git$|.*\\.atom$|.*[\\-._][\\-._].*)[a-zA-Z0-9][a-zA-Z0-9\\-_.]*$"

    def __init__(self, value: str) -> None:
        if not re.match(self._regex, value):
            raise errors.ValidationError(message=f"The slug {value} does not match the regex {self._regex}")
        object.__setattr__(self, "value", value.lower())

    @classmethod
    def from_name(cls, name: str) -> "Slug":
        """Takes a name with any amount of invalid characters and transforms it in a valid slug."""
        lower_case = name.lower()
        no_space = re.sub(r"\s+", "-", lower_case)
        normalized = unicodedata.normalize("NFKD", no_space).encode("ascii", "ignore").decode("utf-8")
        valid_chars_pattern = [r"\w", ".", "_", "-"]
        no_invalid_characters = re.sub(f'[^{"".join(valid_chars_pattern)}]', "-", normalized)
        no_duplicates = re.sub(r"([._-])[._-]+", r"\1", no_invalid_characters)
        valid_start = re.sub(r"^[._-]", "", no_duplicates)
        valid_end = re.sub(r"[._-]$", "", valid_start)
        no_dot_git_or_dot_atom_at_end = re.sub(r"(\.atom|\.git)+$", "", valid_end)
        if len(no_dot_git_or_dot_atom_at_end) == 0:
            raise errors.ValidationError(
                message="The name for the project contains too many invalid characters so a slug could not be generated"
            )
        return cls(no_dot_git_or_dot_atom_at_end)

    def __true_div__(self, other: "Slug") -> str:
        """Joins two slugs into a path fraction without dashes at the beginning or end."""
        if type(self) is not type(other):
            raise errors.ValidationError(
                message=f"A path can be constructed only from 2 slugs, but the 'divisor' is of type {type(other)}"
            )
        return self.value + "/" + other.value
