"""Database adapters and helpers for users."""
import asyncio
import logging
from dataclasses import asdict
from datetime import datetime, timedelta
from functools import wraps
from typing import Any, Callable, Dict, List

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from renku_data_services.base_api.auth import APIUser, only_authenticated
from renku_data_services.errors import errors
from renku_data_services.users.kc_api import IKeycloakAPI
from renku_data_services.users.models import KeycloakAdminEvent, UserInfo, UserInfoUpdate
from renku_data_services.users.orm import LastKeycloakEventTimestamp, UserORM


class UserRepo:
    """An adapter for accessing users from the database."""

    def __init__(self, session_maker: Callable[..., AsyncSession]):
        self.session_maker = session_maker
        self._users_sync = UsersSync(self.session_maker)

    async def initialize(self, kc_api: IKeycloakAPI):
        """Do a total sync of users from Keycloak if there is nothing in the DB."""
        users = await self._get_users()
        if len(users) > 0:
            return
        await self._users_sync.users_sync(kc_api)

    async def _add_api_user(self, user: APIUser) -> UserInfo:
        if not user.id:
            raise errors.Unauthorized(message="The user has to be authenticated to be inserted in the DB.")
        await self._users_sync.update_or_insert_user(
            user_id=user.id,
            first_name=user.first_name,
            last_name=user.last_name,
            email=user.email,
        )
        return UserInfo(
            id=user.id,
            first_name=user.first_name,
            last_name=user.last_name,
            email=user.email,
        )

    @only_authenticated
    async def get_user(self, requested_by: APIUser, id: str) -> UserInfo | None:
        """Get a specific user from the database."""
        if not requested_by.is_admin and requested_by.id != id:
            raise errors.Unauthorized(message="Users are not allowed to lookup other users.")
        async with self.session_maker() as session:
            stmt = select(UserORM).where(UserORM.keycloak_id == id)
            res = await session.execute(stmt)
            orm = res.scalar_one_or_none()
            if not orm and id == requested_by.id:
                return await self._add_api_user(requested_by)
            if not orm:
                return None
            return orm.dump()

    @only_authenticated
    async def get_users(self, requested_by: APIUser, email: str | None = None) -> List[UserInfo]:
        """Get users from the database."""
        if not email and not requested_by.is_admin:
            raise errors.Unauthorized(message="Non-admin users cannot list all users.")
        users = await self._get_users(email)

        def is_api_user_missing() -> bool:
            return not any([requested_by.id == user.id for user in users])

        if not email and is_api_user_missing():
            api_user_info = await self._add_api_user(requested_by)
            users.append(api_user_info)
        return users

    async def _get_users(self, email: str | None = None) -> List[UserInfo]:
        async with self.session_maker() as session:
            stmt = select(UserORM)
            if email:
                stmt = stmt.where(UserORM.email == email)
            res = await session.execute(stmt)
            orms = res.scalars().all()
            return [orm.dump() for orm in orms]


class UsersSync:
    """Sync users from Keycloak to the database."""

    def __init__(
        self,
        session_maker: Callable[..., AsyncSession],
    ):
        self.session_maker = session_maker

    async def _get_user(self, id) -> UserInfo | None:
        """Get a specific user."""
        async with self.session_maker() as session, session.begin():
            stmt = select(UserORM).where(UserORM.keycloak_id == id)
            res = await session.execute(stmt)
            orm = res.scalar_one_or_none()
            return orm.dump() if orm else None

    async def update_or_insert_user(self, user_id: str, **kwargs):
        """Update a user or insert it if it does not exist."""
        async with self.session_maker() as session, session.begin():
            res = await session.execute(select(UserORM).where(UserORM.keycloak_id == user_id))
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

    async def _remove_user(self, user_id: str):
        """Remove a user from the database."""
        async with self.session_maker() as session, session.begin():
            logging.info(f"Removing user with ID {user_id}")
            stmt = delete(UserORM).where(UserORM.keycloak_id == user_id)
            await session.execute(stmt)

    async def users_sync(self, kc_api: IKeycloakAPI):
        """Sync all users from Keycloak into the users database."""
        async with self.session_maker() as session, session.begin():
            logging.info("Starting a total user database sync.")
            kc_users = kc_api.get_users()

            async def _do_update(raw_kc_user: Dict[str, Any]):
                kc_user = UserInfo.from_kc_user_payload(raw_kc_user)
                db_user = await self._get_user(kc_user.id)
                if db_user != kc_user:
                    logging.info(f"Inserting or updating user {db_user} -> {kc_user}")
                    await self.update_or_insert_user(kc_user.id, **asdict(kc_user))

            await asyncio.gather(*[_do_update(u) for u in kc_users])

    async def events_sync(self, kc_api: IKeycloakAPI):
        """Use the events from Keycloak to update the users database."""
        async with self.session_maker() as session, session.begin():
            res_count = await session.execute(select(func.count()).select_from(UserORM))
            count = res_count.scalar() or 0
            if count == 0:
                await self.users_sync(kc_api)
            logging.info("Starting periodic event sync.")
            stmt = select(LastKeycloakEventTimestamp)
            latest_utc_timestamp_orm = (await session.execute(stmt)).scalar_one_or_none()
            previous_sync_latest_utc_timestamp = (
                latest_utc_timestamp_orm.timestamp_utc if latest_utc_timestamp_orm is not None else None
            )
            logging.info(f"The previous sync latest event is {previous_sync_latest_utc_timestamp} UTC")
            now_utc = datetime.utcnow()
            start_date = now_utc.date() - timedelta(days=1)
            logging.info(f"Pulling events with a start date of {start_date} UTC")
            user_events = kc_api.get_user_events(start_date=start_date)
            update_admin_events = kc_api.get_admin_events(
                start_date=start_date, event_types=[KeycloakAdminEvent.CREATE, KeycloakAdminEvent.UPDATE]
            )
            delete_admin_events = kc_api.get_admin_events(
                start_date=start_date, event_types=[KeycloakAdminEvent.DELETE]
            )
            parsed_updates = UserInfoUpdate.from_json_admin_events(update_admin_events)
            parsed_updates.extend(UserInfoUpdate.from_json_user_events(user_events))
            parsed_deletions = UserInfoUpdate.from_json_admin_events(delete_admin_events)
            parsed_updates = sorted(parsed_updates, key=lambda x: x.timestamp_utc)
            parsed_deletions = sorted(parsed_deletions, key=lambda x: x.timestamp_utc)
            if previous_sync_latest_utc_timestamp is not None:
                # Some events have already been processed - filter out old events we have seen
                logging.info(f"Filtering events older than {previous_sync_latest_utc_timestamp}")
                parsed_updates = [u for u in parsed_updates if u.timestamp_utc > previous_sync_latest_utc_timestamp]
                parsed_deletions = [u for u in parsed_deletions if u.timestamp_utc > previous_sync_latest_utc_timestamp]
            latest_update_timestamp = None
            latest_delete_timestamp = None
            for update in parsed_updates:
                logging.info(f"Processing update event {update}")
                await self.update_or_insert_user(update.user_id, **{update.field_name: update.new_value})
                latest_update_timestamp = update.timestamp_utc
            for deletion in parsed_deletions:
                logging.info(f"Processing deletion event {deletion}")
                await self._remove_user(deletion.user_id)
                latest_delete_timestamp = deletion.timestamp_utc
            # Update the latest processed event timestamp
            current_sync_latest_utc_timestamp = latest_update_timestamp
            if latest_delete_timestamp is not None and (
                current_sync_latest_utc_timestamp is None or current_sync_latest_utc_timestamp < latest_delete_timestamp
            ):
                current_sync_latest_utc_timestamp = latest_delete_timestamp
            if current_sync_latest_utc_timestamp is not None:
                if latest_utc_timestamp_orm is None:
                    session.add(LastKeycloakEventTimestamp(current_sync_latest_utc_timestamp))
                    logging.info(
                        f"Inserted the latest sync event timestamp in the database: {current_sync_latest_utc_timestamp}"
                    )
                else:
                    latest_utc_timestamp_orm.timestamp_utc = current_sync_latest_utc_timestamp
                    logging.info(
                        f"Updated the latest sync event timestamp in the database: {current_sync_latest_utc_timestamp}"
                    )
