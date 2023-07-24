from dataclasses import dataclass, field
from typing import Optional, Protocol


class Authenticator(Protocol):
    """Interface for authenticating users."""

    async def authenticate(self, access_token: str) -> "APIUser":
        """Validates the user credentials (i.e. we can say that the user is a valid Renku user)."""
        ...


@dataclass
class APIUser:
    """The model for a user of the API, used for authentication."""

    is_admin: bool = False
    id: Optional[str] = None
    access_token: Optional[str] = field(repr=False, default=None)

    @property
    def is_authenticated(self):
        """Indicates whether the user has sucessfully logged in."""
        return self.id is not None
