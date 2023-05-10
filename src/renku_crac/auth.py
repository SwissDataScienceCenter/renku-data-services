"""Authentication decorators for Sanic."""
from functools import wraps

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

            response = await f(request, *args, **kwargs, user=user)
            return response

        return decorated_function

    return decorator


def only_admins(f):
    """Decorator for a Sanic handler that errors out if the user is not an admin."""

    @wraps(f)
    async def decorated_function(request: Request, user: APIUser, *args, **kwargs):
        if user is None or not user.is_admin:
            raise errors.Unauthorized()

        # the user is authenticated and is an admin
        response = await f(request, *args, **kwargs, user=user)
        return response

    return decorated_function
