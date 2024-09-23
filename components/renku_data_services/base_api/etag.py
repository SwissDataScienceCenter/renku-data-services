"""Enitity tag decorators for Sanic."""

from collections.abc import Callable, Coroutine
from functools import wraps
from typing import Any, Concatenate, ParamSpec, TypeVar

from sanic import Request

from renku_data_services import errors

_T = TypeVar("_T")
_P = ParamSpec("_P")


def if_match_required(
    f: Callable[Concatenate[Request, _P], Coroutine[Any, Any, _T]],
) -> Callable[Concatenate[Request, _P], Coroutine[Any, Any, _T]]:
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


def extract_if_none_match(
    f: Callable[Concatenate[Request, _P], Coroutine[Any, Any, _T]],
) -> Callable[Concatenate[Request, _P], Coroutine[Any, Any, _T]]:
    """Decorator which extracts the "If-None-Match" header if present."""

    @wraps(f)
    async def decorated_function(request: Request, *args: _P.args, **kwargs: _P.kwargs) -> _T:
        etag = request.headers.get("If-None-Match")
        kwargs["etag"] = etag
        response = await f(request, *args, **kwargs)
        return response

    return decorated_function
