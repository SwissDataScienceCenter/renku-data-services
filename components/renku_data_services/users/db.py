"""Database adapters and helpers for users."""
import asyncio
import logging
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from renku_data_services.base_api.auth import APIUser, only_authenticated
from renku_data_services.errors import errors
from renku_data_services.message_queue.db import EventRepository
from renku_data_services.message_queue.interface import IMessageQueue
from renku_data_services.users.kc_api import IKeycloakAPI
from renku_data_services.users.models import KeycloakAdminEvent, UserInfo, UserInfoUpdate
from renku_data_services.users.orm import LastKeycloakEventTimestamp, UserORM


class UserRepo:
    """An adapter for accessing users from the database."""

    def __init__(
        self,
        session_maker: Callable[..., AsyncSession],
        message_queue: IMessageQueue,
        event_repo: EventRepository,
    ):
        self.session_maker = session_maker
        self._users_sync = UsersSync(self.session_maker, message_queue, event_repo)

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
        async with self.session_maker() as session:
            stmt = select(UserORM).where(UserORM.keycloak_id == id)
            res = await session.execute(stmt)
            orm = res.scalar_one_or_none()
            if not orm:
                return None
            return orm.dump()

    @only_authenticated
    async def get_or_create_user(self, requested_by: APIUser, id: str) -> UserInfo | None:
        """Get a specific user from the database and create it potentially if it does not exist.

        If the caller is the same user that is being retrieved and they are authenticated and
        their user information is not in the database then this call adds the user in the DB
        in addition to returning the user information.
        """
        async with self.session_maker() as session, session.begin():
            user = await self.get_user(requested_by=requested_by, id=id)
            if not user and id == requested_by.id:
                return await self._add_api_user(requested_by)
            return user

    @only_authenticated
    async def get_users(self, requested_by: APIUser, email: str | None = None) -> List[UserInfo]:
        """Get users from the database."""
        if not email and not requested_by.is_admin:
            raise errors.Unauthorized(message="Non-admin users cannot list all users.")
        users = await self._get_users(email)

        is_api_user_missing = not any([requested_by.id == user.id for user in users])

        if not email and is_api_user_missing:
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
        message_queue: IMessageQueue,
        event_repo: EventRepository,
    ):
        self.session_maker = session_maker
        self.message_queue: IMessageQueue = message_queue
        self.event_repo: EventRepository = event_repo

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
        if existing_user:
            cm = self.message_queue.user_updated_message(
                id=user_id,
                first_name=kwargs.get("first_name", existing_user.first_name),
                last_name=kwargs.get("last_name", existing_user.last_name),
                email=kwargs.get("email", existing_user.email),
            )
        else:
            cm = self.message_queue.user_added_message(
                id=user_id,
                first_name=kwargs.get("first_name"),
                last_name=kwargs.get("last_name"),
                email=kwargs.get("email"),
            )
        async with cm as message:
            async with self.session_maker() as session, session.begin():
                kwargs.pop("keycloak_id", None)
                kwargs.pop("id", None)
                if not existing_user:
                    new_user = UserORM(keycloak_id=user_id, **kwargs)
                    session.add(new_user)
                else:
                    session.add(existing_user)  # reattach to session
                    for field_name, field_value in kwargs.items():
                        if getattr(existing_user, field_name, None) != field_value:
                            setattr(existing_user, field_name, field_value)
                await message.persist(self.event_repo)

    async def _remove_user(self, user_id: str):
        """Remove a user from the database."""
        async with self.message_queue.user_removed_message(id=user_id) as message:
            async with self.session_maker() as session, session.begin():
                logging.info(f"Removing user with ID {user_id}")
                stmt = delete(UserORM).where(UserORM.keycloak_id == user_id)
                await session.execute(stmt)
                await message.persist(self.event_repo)

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
