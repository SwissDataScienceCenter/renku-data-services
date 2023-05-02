"""Dummy adapter for communicating with Keycloak to be used for testing."""
from asyncio import Lock
from typing import Dict, Optional
from uuid import uuid4

import models


class DummyUserStore:
    """A dummy adapter for keycloak. By default it will create and return users that do not exist."""

    def __init__(self, *, user_always_exists: bool = True):
        self._users: Dict[str, models.User] = {}
        self._lock = Lock()
        self._user_always_exists = user_always_exists

    @property
    def user_always_exists(self) -> bool:
        """If true then every query for a user will make a user that matches the query."""
        return self._user_always_exists

    @user_always_exists.setter
    def user_always_exists(self, value: bool):
        """Control over the users that are queried should exist or not."""
        self._user_always_exists = value

    async def get_user_by_id(self, id: str) -> Optional[models.User]:
        """Get a user by their unique id."""
        async with self._lock:
            user = self._users.get(id)
            if not user and self._user_always_exists:
                username = f"{id}@email.com"
                user = models.User(keycloak_id=id, username=username)
                self._users[id] = user
            return user

    async def get_user_by_username(self, username: str) -> Optional[models.User]:
        """Get a user by their username."""
        async with self._lock:
            user = next((user for user in self._users.values() if user.username == username), None)
            if not user and self._user_always_exists:
                id = str(uuid4())
                user = models.User(username=username, keycloak_id=id)
                self._users[id] = user
            return user
