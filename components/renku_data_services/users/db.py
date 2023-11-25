"""Database adapters and helpers for users."""
from functools import wraps
from typing import Callable, List

from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from renku_data_services.base_api.auth import APIUser
from renku_data_services.errors import errors
from renku_data_services.users.models import UserInfo
from renku_data_services.users.orm import UserORM


def _authenticated(f):
    """Decorator that errors out if the user is not authenticated.

    It expects the APIUser model to be a named parameter in the decorated function or
    to be the first parameter (after self).
    """

    @wraps(f)
    async def decorated_function(self, *args, **kwargs):
        api_user = None
        if "requested_by" in kwargs:
            api_user = kwargs["api_user"]
        elif len(args) >= 1:
            api_user = args[0]
        if api_user is None or not api_user.is_authenticated:
            raise errors.Unauthorized(message="You have to be authenticated to perform this operation.")

        # the user is authenticated and is an admin
        response = await f(self, *args, **kwargs)
        return response

    return decorated_function


class UserRepo:
    """An adapter for accessing users from the database."""

    def __init__(self, session_maker: Callable[..., AsyncSession]):
        self.session_maker = session_maker

    @_authenticated
    async def get_user(self, requested_by: APIUser, id: str) -> UserInfo | None:
        """Get a specific user from the database."""
        if not requested_by.is_admin or requested_by.id != id:
            raise errors.Unauthorized(message="Users are not allowed to lookup other users.")
        async with self.session_maker() as session:
            stmt = select(UserORM).where(UserORM.keycloak_id == id)
            res = await session.execute(stmt)
            orm = res.scalar_one_or_none()
            if not orm:
                return None
            return orm.dump()

    @_authenticated
    async def get_users(self, requested_by: APIUser, email: str | None = None) -> List[UserInfo]:
        """Get user from the database."""
        if not email and not requested_by.is_admin:
            raise errors.Unauthorized(message="Non-admin users cannot list all users.")
        async with self.session_maker() as session:
            stmt = select(UserORM)
            if email:
                stmt.where(UserORM.email == email)
            res = await session.execute(stmt)
            orms = res.scalars().all()
            return [orm.dump() for orm in orms]
