"""Authentication decorators for Sanic."""
from functools import wraps
from typing import cast

from sanic import Request

from models import APIUser, Authenticator, errors


def authenticate(authneticator: Authenticator):
    """Decorator for a Sanic handler that adds the APIUser model to the context.

    The APIUser is present for admins, non-admins and users who are not logged in.
    """

    def decorator(f):
        @wraps(f)
        async def decorated_function(request: Request, *args, **kwargs):
            token = request.headers.get("Authorization")
            user = APIUser()
            if token is not None and len(token) >= 8:
                user = await authneticator.authenticate(token[7:])

            request.ctx.user = user
            response = await f(request, *args, **kwargs)
            return response

        return decorated_function

    return decorator


def only_admins(f):
    """Decorator for a Sanic handler that errors out if the user is not an admin."""

    @wraps(f)
    async def decorated_function(request: Request, *args, **kwargs):
        user = getattr(request.ctx, "user", None)
        if user is None or cast(APIUser, user).access_token is None or not cast(APIUser, request.ctx.user).is_admin:
            raise errors.Unauthorized()

        # the user is authenticated and is an admin
        response = await f(request, *args, **kwargs)
        return response

    return decorated_function
