"""Authentication that is compatible with the tokens sent to the notebook service."""

from collections.abc import Callable, Coroutine
from functools import wraps
from typing import Any, Concatenate, ParamSpec, TypeVar

from sanic import Request

from renku_data_services.base_models import AnonymousAPIUser, APIUser, AuthenticatedAPIUser, Authenticator

_T = TypeVar("_T")
_P = ParamSpec("_P")


def notebooks_internal_gitlab_authenticate(
    authenticator: Authenticator,
) -> Callable[
    [Callable[Concatenate[Request, AuthenticatedAPIUser | AnonymousAPIUser, APIUser, _P], Coroutine[Any, Any, _T]]],
    Callable[Concatenate[Request, AuthenticatedAPIUser | AnonymousAPIUser, _P], Coroutine[Any, Any, _T]],
]:
    """Decorator for a Sanic handler that that adds a notebooks user."""

    def decorator(
        f: Callable[
            Concatenate[Request, AuthenticatedAPIUser | AnonymousAPIUser, APIUser, _P], Coroutine[Any, Any, _T]
        ],
    ) -> Callable[Concatenate[Request, AuthenticatedAPIUser | AnonymousAPIUser, _P], Coroutine[Any, Any, _T]]:
        @wraps(f)
        async def decorated_function(
            request: Request,
            user: AuthenticatedAPIUser | AnonymousAPIUser,
            *args: _P.args,
            **kwargs: _P.kwargs,
        ) -> _T:
            access_token = str(request.headers.get("Gitlab-Access-Token"))
            internal_gitlab_user = await authenticator.authenticate(access_token, request)
            return await f(request, user, internal_gitlab_user, *args, **kwargs)

        return decorated_function

    return decorator
