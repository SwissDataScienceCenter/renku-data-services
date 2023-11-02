"""Dummy adapter for communicating with Keycloak to be used for testing."""
import json
from asyncio import Lock
from dataclasses import dataclass
from typing import Dict, Optional

from sanic import Request

import renku_data_services.base_models as base_models


class DummyUserStore:
    """A dummy adapter for keycloak. By default it will create and return users that do not exist."""

    def __init__(self, *, user_always_exists: bool = True):
        self._users: Dict[str, base_models.User] = {}
        self._lock = Lock()
        self.user_always_exists = user_always_exists

    async def get_user_by_id(self, id: str, access_token: str) -> Optional[base_models.User]:
        """Get a user by their unique id."""
        async with self._lock:
            user = self._users.get(id)
            if not user and self.user_always_exists:
                user = base_models.User(
                    keycloak_id=id,
                )
                self._users[id] = user
            return user


@dataclass
class DummyAuthenticator:
    """
    Dummy authenticator that pretends to call Keycloak, not suitable for production.

    Will try to parse the access token as json and assign any values that match to the ApiUser returned.
    """

    token_field = "Authorization"  # nosec: B105

    async def authenticate(self, access_token: str, request: Request) -> base_models.APIUser:
        """Indicates whether the user has sucessfully logged in."""
        user_props = {}
        try:
            user_props = json.loads(access_token)
        except:  # noqa: E722 # nosec: B110
            pass
        return base_models.APIUser(
            is_admin=user_props.get("is_admin") if user_props.get("is_admin") else False,  # type: ignore[arg-type]
            id=user_props.get("id") if user_props.get("id") else "some-id",
            access_token=access_token,
            name=user_props.get("name") if user_props.get("name") else "John Doe",
        )
