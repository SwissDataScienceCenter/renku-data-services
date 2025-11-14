"""Authentication decorators for Sanic."""

import asyncio
import re
from collections.abc import Callable, Coroutine
from functools import wraps
from typing import Any, Concatenate, ParamSpec, TypeVar, cast

from sanic import Request

from renku_data_services import errors
from renku_data_services.base_models import AnyAPIUser, APIUser, Authenticator

_T = TypeVar("_T")
_P = ParamSpec("_P")


def authenticate(
    authenticator: Authenticator,
) -> Callable[
    [Callable[Concatenate[Request, AnyAPIUser, _P], Coroutine[Any, Any, _T]]],
    Callable[Concatenate[Request, _P], Coroutine[Any, Any, _T]],
]:
    """Decorator for a Sanic handler that adds the APIUser model to the context.

    The APIUser is present for admins, non-admins and users who are not logged in.
    """

    def decorator(
        f: Callable[Concatenate[Request, AnyAPIUser, _P], Coroutine[Any, Any, _T]],
    ) -> Callable[Concatenate[Request, _P], Coroutine[Any, Any, _T]]:
        @wraps(f)
        async def decorated_function(request: Request, *args: _P.args, **kwargs: _P.kwargs) -> _T:
            token = request.headers.get(authenticator.token_field)
            user = await authenticator.authenticate(token or "", request)
            response = await f(request, user, *args, **kwargs)
            return response

        return decorated_function

    return decorator


def authenticate_2(
    authenticator1: Authenticator,
    authenticator2: Authenticator,
) -> Callable[
    [Callable[Concatenate[Request, AnyAPIUser, AnyAPIUser, _P], Coroutine[Any, Any, _T]]],
    Callable[Concatenate[Request, _P], Coroutine[Any, Any, _T]],
]:
    """Decorator for a Sanic handler that adds the APIUser when another authentication has already been done."""

    def decorator(
        f: Callable[Concatenate[Request, AnyAPIUser, AnyAPIUser, _P], Coroutine[Any, Any, _T]],
    ) -> Callable[Concatenate[Request, _P], Coroutine[Any, Any, _T]]:
        @wraps(f)
        async def decorated_function(request: Request, *args: _P.args, **kwargs: _P.kwargs) -> _T:
            token1 = request.headers.get(authenticator1.token_field)
            token2 = request.headers.get(authenticator2.token_field)
            user1: AnyAPIUser
            user2: AnyAPIUser
            [user1, user2] = await asyncio.gather(
                authenticator1.authenticate(token1 or "", request),
                authenticator2.authenticate(token2 or "", request),
            )
            response = await f(request, user1, user2, *args, **kwargs)
            return response

        return decorated_function

    return decorator


def validate_path_user_id(
    f: Callable[Concatenate[Request, _P], Coroutine[Any, Any, _T]],
) -> Callable[Concatenate[Request, _P], Coroutine[Any, Any, _T]]:
    """Decorator for a Sanic handler that validates the user_id or member_id path parameter."""
    _path_user_id_regex = re.compile(r"^[A-Za-z0-9]{1}[A-Za-z0-9-]+$")

    @wraps(f)
    async def decorated_function(request: Request, *args: _P.args, **kwargs: _P.kwargs) -> _T:
        user_id: str | None = cast(str | None, kwargs.get("user_id"))
        member_id: str | None = cast(str | None, kwargs.get("member_id"))
        if user_id and member_id:
            raise errors.ProgrammingError(
                message="Validating the user ID in a request path failed because matches for both"
                " 'user_id' and 'member_id' were found in the request handler parameters but only "
                "one match was expected."
            )
        user_id = user_id or member_id
        if not user_id:
            raise errors.ProgrammingError(
                message="Could not find 'user_id' or 'member_id' in the keyword arguments for the handler "
                "in order to validate it."
            )
        if not _path_user_id_regex.match(user_id):
            raise errors.ValidationError(
                message=f"The 'user_id' or 'member_id' path parameter {user_id} does not match the requried "
                f"regex {_path_user_id_regex}"
            )

        return await f(request, *args, **kwargs)

    return decorated_function


def only_admins(
    f: Callable[Concatenate[Request, APIUser, _P], Coroutine[Any, Any, _T]],
) -> Callable[Concatenate[Request, APIUser, _P], Coroutine[Any, Any, _T]]:
    """Decorator for a Sanic handler that errors out if the user is not an admin."""

    @wraps(f)
    async def decorated_function(request: Request, user: APIUser, *args: _P.args, **kwargs: _P.kwargs) -> _T:
        if user is None or user.access_token is None:
            raise errors.UnauthorizedError(
                message="Please provide valid access credentials in the Authorization header."
            )
        if not user.is_admin:
            raise errors.ForbiddenError(message="You do not have the required permissions for this operation.")

        # the user is authenticated and is an admin
        response = await f(request, user, *args, **kwargs)
        return response

    return decorated_function


def only_authenticated(f: Callable[_P, Coroutine[Any, Any, _T]]) -> Callable[_P, Coroutine[Any, Any, _T]]:
    """Decorator that errors out if the user is not authenticated.

    It looks for APIUser in the named or unnamed parameters.
    """

    @wraps(f)
    async def decorated_function(*args: _P.args, **kwargs: _P.kwargs) -> _T:
        api_user = None
        if "requested_by" in kwargs and isinstance(kwargs["requested_by"], APIUser):
            api_user = kwargs["requested_by"]
        elif "user" in kwargs and isinstance(kwargs["user"], APIUser):
            api_user = kwargs["user"]
        elif len(args) >= 1:
            api_user_search = [a for a in args if isinstance(a, APIUser)]
            if len(api_user_search) == 1:
                api_user = api_user_search[0]
            else:
                raise errors.ProgrammingError(
                    detail="Found no or more than one valid non-keyword APIUser arguments when "
                    "authenticating user, expected only one."
                )

        if api_user is None or not api_user.is_authenticated:
            raise errors.UnauthorizedError(message="You have to be authenticated to perform this operation.")

        # the user is authenticated
        response = await f(*args, **kwargs)
        return response

    return decorated_function


def require_role(
    role: str,
) -> Callable[
    [Callable[Concatenate[Request, APIUser, _P], Coroutine[Any, Any, _T]]],
    Callable[Concatenate[Request, APIUser, _P], Coroutine[Any, Any, _T]],
]:
    """Decorator for a Sanic handler that errors out if the user does not have the specified role.

    Args:
        role: The role name to check for (e.g., "alertmanager-webhook")
    """

    def decorator(
        f: Callable[Concatenate[Request, APIUser, _P], Coroutine[Any, Any, _T]],
    ) -> Callable[Concatenate[Request, APIUser, _P], Coroutine[Any, Any, _T]]:
        @wraps(f)
        async def decorated_function(request: Request, user: APIUser, *args: _P.args, **kwargs: _P.kwargs) -> _T:
            if user is None or user.access_token is None:
                raise errors.UnauthorizedError(
                    message="Please provide valid access credentials in the Authorization header."
                )
            if role not in user.roles:
                raise errors.ForbiddenError(message=f"You do not have the required role '{role}' for this operation.")

            # the user is authenticated and has the required role
            response = await f(request, user, *args, **kwargs)
            return response

        return decorated_function

    return decorator
