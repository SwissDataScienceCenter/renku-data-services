"""Enitity tag decorators for Sanic."""

from functools import wraps

from sanic import Request

from renku_data_services import errors


def if_match_required(f):
    """Decorator that errors out if the "If-Match" header is not present."""

    @wraps(f)
    async def decorated_function(request: Request, *args, **kwargs):
        etag = request.headers.get("If-Match")
        if etag is None:
            raise errors.PreconditionRequiredError(message="If-Match header not provided.")

        response = await f(request, *args, **kwargs, etag=etag)
        return response

    return decorated_function
