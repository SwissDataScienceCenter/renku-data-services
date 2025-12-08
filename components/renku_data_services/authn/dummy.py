"""Dummy adapter for communicating with Keycloak to be used for testing."""

import contextlib
import json
from asyncio import Lock
from dataclasses import dataclass
from typing import Optional

from sanic import Request
from ulid import ULID

import renku_data_services.base_models as base_models


class DummyUserStore:
    """A dummy adapter for keycloak. By default, it will create and return users that do not exist."""

    def __init__(self, *, user_always_exists: bool = True) -> None:
        self._users: dict[str, base_models.User] = {}
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
    """Dummy authenticator that pretends to call Keycloak, not suitable for production.

    Will try to parse the access token as json and assign any values that match to the ApiUser returned.
    """

    token_field = "Authorization"  # nosec: B105
    anon_id_header_key: str = "Renku-Auth-Anon-Id"
    anon_id_cookie_name: str = "Renku-Auth-Anon-Id"

    async def authenticate(self, access_token: str, request: Request) -> base_models.APIUser:
        """Indicates whether the user has successfully logged in."""
        access_token = request.headers.get(self.token_field) or ""
        if not access_token or len(access_token) == 0:
            # Try to get an anonymous user ID if the validation of keycloak credentials failed
            anon_id = request.headers.get(self.anon_id_header_key)
            if anon_id is None:
                anon_id = request.cookies.get(self.anon_id_cookie_name)
            if anon_id is None:
                anon_id = f"anon-{str(ULID())}"
            return base_models.AnonymousAPIUser(id=str(anon_id))

        access_token = access_token.removeprefix("Bearer ").removeprefix("bearer ")
        user_props = {}
        with contextlib.suppress(Exception):
            user_props = json.loads(access_token)

        is_set = bool(
            user_props.get("id")
            or user_props.get("full_name")
            or user_props.get("is_admin") is not None
            or user_props.get("first_name")
            or user_props.get("last_name")
            or user_props.get("email")
        )

        return base_models.APIUser(
            is_admin=user_props.get("is_admin", False),
            id=user_props.get("id", "some-id") if is_set else None,
            access_token=access_token,
            first_name=user_props.get("first_name", "John") if is_set else None,
            last_name=user_props.get("last_name", "Doe") if is_set else None,
            email=user_props.get("email", "john.doe@gmail.com") if is_set else None,
            full_name=user_props.get("full_name", "John Doe") if is_set else None,
            refresh_token=request.headers.get("Renku-Auth-Refresh-Token"),
            roles=user_props.get("roles", []),
        )
