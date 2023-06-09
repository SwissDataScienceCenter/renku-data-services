"""Dummy adapter for communicating with Keycloak to be used for testing."""
from asyncio import Lock
from dataclasses import dataclass
from typing import Dict, Optional

import models


@dataclass
class _DummyUser:
    id: str
    username: str


class DummyUserStore:
    """A dummy adapter for keycloak. By default it will create and return users that do not exist."""

    def __init__(self, *, user_always_exists: bool = True):
        self._users: Dict[str, _DummyUser] = {}
        self._lock = Lock()
        self.user_always_exists = user_always_exists

    async def get_user_by_id(self, id: str, access_token: str) -> Optional[models.User]:
        """Get a user by their unique id."""
        async with self._lock:
            user = self._users.get(id)
            if not user and self.user_always_exists:
                username = f"{id}@email.com"
                user = _DummyUser(id=id, username=username)
                self._users[id] = user
            return models.User(keycloak_id=id)


@dataclass
class DummyAuthenticator:
    """Dummy authenticator that pretends to call Keycloak, not suitable for production."""

    logged_in: bool = True
    admin: bool = False

    async def authenticate(self, access_token: str) -> models.APIUser:
        """Indicates whether the user has sucessfully logged in."""

        return models.APIUser(is_admin=self.admin, id="some-id", access_token=access_token)
