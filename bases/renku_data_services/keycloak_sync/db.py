"""Database adapters and helpers."""
import logging
from typing import Callable, List

from sqlalchemy import create_engine, delete, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from renku_data_services.users.models import UserInfo, UserInfoUpdate
from renku_data_services.users.orm import UserORM


class DB:
    """Database adapter for users."""

    def __init__(
        self, sync_sqlalchemy_url: str, async_sqlalchemy_url: str, debug: bool = False
    ):
        self.engine = create_async_engine(async_sqlalchemy_url, echo=debug)
        self.sync_engine = create_engine(sync_sqlalchemy_url, echo=debug)
        self.session_maker: Callable[..., AsyncSession] = sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )  # type: ignore[call-overload]

    async def get_users(self) -> List[UserInfo]:
        """Get all users."""
        async with self.session_maker() as session, session.begin():
            stmt = select(UserORM)
            res = await session.execute(stmt)
            orms = res.scalars().all()
            return [orm.dump() for orm in orms]

    async def get_user(self, id) -> UserInfo | None:
        """Get a specific user."""
        async with self.session_maker() as session, session.begin():
            stmt = select(UserORM).where(UserORM.keycloak_id == id)
            res = await session.execute(stmt)
            orm = res.scalar_one_or_none()
            return orm.dump() if orm else None

    async def update_or_insert_user(self, user_id: str, **kwargs):
        """Update a user or insert it if it does not exist."""
        async with self.session_maker() as session, session.begin():
            res = await session.execute(select(UserORM).where(UserORM.id == user_id))
            existing_user = res.scalar_one_or_none()
            kwargs.pop("keycloak_id", None)
            kwargs.pop("id", None)
            if not existing_user:
                new_user = UserORM(keycloak_id=user_id, **kwargs)
                session.add(new_user)
            else:
                for field_name, field_value in kwargs.items():
                    if getattr(existing_user, field_name, None) != field_value:
                        setattr(existing_user, field_name, field_value)

    async def process_updates(self, updates: List[UserInfoUpdate]):
        """Process a series of updates from keycloak events."""
        async with self.session_maker() as session, session.begin():
            for update in updates:
                await self.update_or_insert_user(update.user_id, **{update.field_name: update.new_value})

    async def remove_user(self, user_id: str):
        """Remove a user from the database."""
        async with self.session_maker() as session, session.begin():
            logging.info(f"Removing user with ID {user_id}")
            stmt = delete(UserORM).where(UserORM.keycloak_id == user_id)
            await session.execute(stmt)
