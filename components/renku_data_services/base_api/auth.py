"""Authentication decorators for Sanic."""

import re
from collections.abc import Callable, Coroutine
from functools import wraps
from typing import Any, Concatenate, ParamSpec, TypeVar, cast

from sanic import HTTPResponse, Request
from ulid import ULID

from renku_data_services import errors
from renku_data_services.base_models import AnonymousAPIUser, APIUser, AuthenticatedAPIUser, Authenticator

_T = TypeVar("_T")
_P = ParamSpec("_P")


def authenticate(
    authenticator: Authenticator,
) -> Callable[
    [Callable[Concatenate[Request, APIUser, _P], Coroutine[Any, Any, _T]]],
    Callable[Concatenate[Request, _P], Coroutine[Any, Any, _T]],
]:
    """Decorator for a Sanic handler that adds the APIUser model to the context.

    The APIUser is present for admins, non-admins and users who are not logged in.
    """

    def decorator(
        f: Callable[Concatenate[Request, APIUser, _P], Coroutine[Any, Any, _T]],
    ) -> Callable[Concatenate[Request, _P], Coroutine[Any, Any, _T]]:
        @wraps(f)
        async def decorated_function(request: Request, *args: _P.args, **kwargs: _P.kwargs) -> _T:
            token = request.headers.get(authenticator.token_field)
            user = APIUser()
            if token is not None and len(token) >= 8:
                token = token.removeprefix("Bearer ").removeprefix("bearer ")
                user = await authenticator.authenticate(token, request)

            response = await f(request, user, *args, **kwargs)
            return response

        return decorated_function

    return decorator


async def _authenticate(authenticator: Authenticator, request: Request) -> AuthenticatedAPIUser:
    token = request.headers.get(authenticator.token_field)
    if token is None or len(token) < 7:
        raise errors.UnauthorizedError(message="You have to log in to access this endpoint.", quiet=True)

    token = token.removeprefix("Bearer ").removeprefix("bearer ")
    user = await authenticator.authenticate(token, request)
    if not user.is_authenticated or user.id is None or user.access_token is None or user.refresh_token is None:
        raise errors.UnauthorizedError(message="You have to log in to access this endpoint.", quiet=True)
    if not user.email:
        raise errors.ProgrammingError(
            message="Expected the user's email to be present after authentication", quiet=True
        )

    return AuthenticatedAPIUser(
        id=user.id,
        access_token=user.access_token,
        full_name=user.full_name,
        first_name=user.first_name,
        last_name=user.last_name,
        email=user.email,
        is_admin=user.is_admin,
        refresh_token=user.refresh_token,
    )


def authenticated_or_anonymous(
    authenticator: Authenticator,
) -> Callable[
    [Callable[Concatenate[Request, AuthenticatedAPIUser | AnonymousAPIUser, _P], Coroutine[Any, Any, HTTPResponse]]],
    Callable[Concatenate[Request, _P], Coroutine[Any, Any, HTTPResponse]],
]:
    """Decorator for a Sanic handler that adds the APIUser or AnonymousAPIUser model to the handler."""

    anon_id_header_key: str = "Renku-Auth-Anon-Id"
    anon_id_cookie_name: str = "Renku-Auth-Anon-Id"

    def decorator(
        f: Callable[
            Concatenate[Request, AuthenticatedAPIUser | AnonymousAPIUser, _P], Coroutine[Any, Any, HTTPResponse]
        ],
    ) -> Callable[Concatenate[Request, _P], Coroutine[Any, Any, HTTPResponse]]:
        @wraps(f)
        async def decorated_function(request: Request, *args: _P.args, **kwargs: _P.kwargs) -> HTTPResponse:
            try:
                user: AnonymousAPIUser | AuthenticatedAPIUser = await _authenticate(authenticator, request)
            except errors.UnauthorizedError:
                # TODO: set the cookie on the user side if it is not set
                # perhaps this will have to be done with another decorator...
                # NOTE: The header takes precedence over the cookie
                anon_id: str | None = request.headers.get(anon_id_header_key)
                if anon_id is None:
                    anon_id = request.cookies.get(anon_id_cookie_name)
                if anon_id is None:
                    anon_id = f"anon-{str(ULID())}"
                user = AnonymousAPIUser(id=anon_id)

            response = await f(request, user, *args, **kwargs)
            return response

        return decorated_function

    return decorator


def validate_path_project_id(
    f: Callable[Concatenate[Request, _P], Coroutine[Any, Any, _T]],
) -> Callable[Concatenate[Request, _P], Coroutine[Any, Any, _T]]:
    """Decorator for a Sanic handler that validates the project_id path parameter."""
    _path_project_id_regex = re.compile(r"^[A-Za-z0-9]{26}$")

    @wraps(f)
    async def decorated_function(request: Request, *args: _P.args, **kwargs: _P.kwargs) -> _T:
        project_id = cast(str | None, kwargs.get("project_id"))
        if not project_id:
            raise errors.ProgrammingError(
                message="Could not find 'project_id' in the keyword arguments for the handler in order to validate it."
            )
        if not _path_project_id_regex.match(project_id):
            raise errors.ValidationError(
                message=f"The 'project_id' path parameter {project_id} does not match the required "
                f"regex {_path_project_id_regex}"
            )

        return await f(request, *args, **kwargs)

    return decorated_function


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


def internal_gitlab_authenticate(
    authenticator: Authenticator,
) -> Callable[
    [Callable[Concatenate[Request, APIUser, APIUser, _P], Coroutine[Any, Any, _T]]],
    Callable[Concatenate[Request, APIUser, _P], Coroutine[Any, Any, _T]],
]:
    """Decorator for a Sanic handler that that adds a user for the internal gitlab user."""

    def decorator(
        f: Callable[Concatenate[Request, APIUser, APIUser, _P], Coroutine[Any, Any, _T]],
    ) -> Callable[Concatenate[Request, APIUser, _P], Coroutine[Any, Any, _T]]:
        @wraps(f)
        async def decorated_function(
            request: Request,
            user: APIUser,
            *args: _P.args,
            **kwargs: _P.kwargs,
        ) -> _T:
            access_token = str(request.headers.get("Gitlab-Access-Token"))
            internal_gitlab_user = await authenticator.authenticate(access_token, request)
            return await f(request, user, internal_gitlab_user, *args, **kwargs)

        return decorated_function

    return decorator
