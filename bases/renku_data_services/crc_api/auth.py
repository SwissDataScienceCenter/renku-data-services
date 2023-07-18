"""Authentication decorators for Sanic."""
from functools import wraps

from renku_data_services.models import errors
from renku_data_services.models.crc import APIUser, Authenticator
from sanic import Request


def authenticate(authenticator: Authenticator):
    """Decorator for a Sanic handler that adds the APIUser model to the context.

    The APIUser is present for admins, non-admins and users who are not logged in.
    """

    def decorator(f):
        @wraps(f)
        async def decorated_function(request: Request, *args, **kwargs):
            token = request.headers.get("Authorization")
            user = APIUser()
            if token is not None and len(token) >= 8:
                user = await authenticator.authenticate(token[7:])

            response = await f(request, *args, **kwargs, user=user)
            return response

        return decorated_function

    return decorator


def only_admins(f):
    """Decorator for a Sanic handler that errors out if the user is not an admin."""

    @wraps(f)
    async def decorated_function(request: Request, user: APIUser, *args, **kwargs):
        if user is None or user.access_token is None:
            raise errors.Unauthorized(message="Please provide valid access credentials in the Authorization header.")
        if not user.is_admin:
            raise errors.Unauthorized(message="You do not have the reuqired permissions for this operation.")

        # the user is authenticated and is an admin
        response = await f(request, *args, **kwargs, user=user)
        return response

    return decorated_function
