"""Base models shared by services."""
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Protocol

from sanic import Request


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
    name: Optional[str] = None

    @property
    def is_authenticated(self):
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
        self, user: APIUser, project_ids: List[str], min_access_level: GitlabAccessLevel
    ) -> List[str]:
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
