"""Authentication decorators for Sanic."""
from functools import wraps

from sanic import Request

from renku_data_services import errors
from renku_data_services.base_models import APIUser, Authenticator


def authenticate(authenticator: Authenticator):
    """Decorator for a Sanic handler that adds the APIUser model to the context.

    The APIUser is present for admins, non-admins and users who are not logged in.
    """

    def decorator(f):
        @wraps(f)
        async def decorated_function(request: Request, *args, **kwargs):
            token = request.headers.get(authenticator.token_field)
            user = APIUser()
            if token is not None and len(token) >= 8:
                token = token.removeprefix("Bearer ").removeprefix("bearer ")
                user = await authenticator.authenticate(token, request)

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
            raise errors.Unauthorized(message="You do not have the required permissions for this operation.")

        # the user is authenticated and is an admin
        response = await f(request, *args, **kwargs, user=user)
        return response

    return decorated_function


def only_authenticated(f):
    """Decorator that errors out if the user is not authenticated.

    It looks for APIUser in the named or unnamed poarameters.
    """

    @wraps(f)
    async def decorated_function(self, *args, **kwargs):
        import logging

        logging.error(f"Receiving args: {args}, kwargs{kwargs}")
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
                    detail="Found two valid non-keyword APIUser arguments when authenticating user, expected only one."
                )

        if api_user is None or not api_user.is_authenticated:
            raise errors.Unauthorized(message="You have to be authenticated to perform this operation.")

        # the user is authenticated
        response = await f(self, *args, **kwargs)
        return response

    return decorated_function
