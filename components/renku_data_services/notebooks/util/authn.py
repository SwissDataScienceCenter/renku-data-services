"""Authentication that is compatible with the tokens sent to the notebook service."""

from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass
from functools import wraps
from typing import Any, Concatenate, ParamSpec, TypeVar

from sanic import Request

from renku_data_services.errors import errors
from renku_data_services.notebooks.api.classes.user import AnonymousUser, RegisteredUser
from renku_data_services.notebooks.config import _NotebooksConfig

_T = TypeVar("_T")
_P = ParamSpec("_P")


@dataclass
class NotebooksAuthenticator:
    """Authentication for notebooks endpoints."""

    config: _NotebooksConfig
    token_field: str = "Authorization"

    def authenticate(self, request: Request) -> RegisteredUser | AnonymousUser:
        """Validate the tokens and ensure the user is signed in."""
        headers_dict: dict[str, str] = {str(k): str(v) for (k, v) in request.headers.items()}
        user: RegisteredUser | AnonymousUser = RegisteredUser(headers_dict)
        if not self.config.anonymous_sessions_enabled and not user.authenticated:
            raise errors.Unauthorized(message="You have to be authenticated to perform this operation.")
        if not user.authenticated:
            user = AnonymousUser(headers_dict, self.config.git.url)
        return user


def notebooks_authenticate(
    authenticator: NotebooksAuthenticator,
) -> Callable[
    [Callable[Concatenate[Request, RegisteredUser | AnonymousUser, _P], Awaitable[_T]]],
    Callable[Concatenate[Request, _P], Coroutine[Any, Any, _T]],
]:
    """Decorator for a Sanic handler that that adds a notebooks user."""

    def decorator(
        f: Callable[Concatenate[Request, RegisteredUser | AnonymousUser, _P], Awaitable[_T]],
    ) -> Callable[Concatenate[Request, _P], Coroutine[Any, Any, _T]]:
        @wraps(f)
        async def decorated_function(request: Request, *args: _P.args, **kwargs: _P.kwargs) -> _T:
            user = authenticator.authenticate(request)
            return await f(request, user, *args, **kwargs)

        return decorated_function

    return decorator
