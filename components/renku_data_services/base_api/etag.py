"""Enitity tag decorators for Sanic."""

from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Concatenate, ParamSpec, TypeVar

from sanic import Request

from renku_data_services import errors

_T = TypeVar("_T")
_P = ParamSpec("_P")


def if_match_required(
    f: Callable[Concatenate[Request, _P], Awaitable[_T]],
) -> Callable[Concatenate[Request, _P], Awaitable[_T]]:
    """Decorator that errors out if the "If-Match" header is not present."""

    @wraps(f)
    async def decorated_function(request: Request, *args: _P.args, **kwargs: _P.kwargs) -> _T:
        etag = request.headers.get("If-Match")
        if etag is None:
            raise errors.PreconditionRequiredError(message="If-Match header not provided.")

        kwargs["etag"] = etag
        response = await f(request, *args, **kwargs)
        return response

    return decorated_function
