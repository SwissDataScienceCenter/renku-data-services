"""Dummy adapter for communicating with Keycloak to be used for testing."""
from asyncio import Lock
from dataclasses import dataclass
from typing import Dict, Optional
from uuid import uuid4

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

    async def get_user_by_id(self, id: str) -> Optional[models.User]:
        """Get a user by their unique id."""
        async with self._lock:
            user = self._users.get(id)
            if not user and self.user_always_exists:
                username = f"{id}@email.com"
                user = _DummyUser(id=id, username=username)
                self._users[id] = user
            return models.User(keycloak_id=id)

    async def get_user_by_username(self, username: str) -> Optional[models.User]:
        """Get a user by their username."""
        async with self._lock:
            user = next((user for user in self._users.values() if user.username == username), None)
            if not user and self.user_always_exists:
                id = str(uuid4())
                self._users[id] = _DummyUser(id=id, username=username)
                return models.User(keycloak_id=id)
            return models.User(keycloak_id=user.id) if user is not None else None
