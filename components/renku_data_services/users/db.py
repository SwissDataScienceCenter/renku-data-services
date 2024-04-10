"""Database adapters and helpers for users."""

import logging
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from renku_data_services.base_api.auth import APIUser, only_authenticated
from renku_data_services.errors import errors
from renku_data_services.message_queue.avro_models.io.renku.events.v1.user_added import UserAdded
from renku_data_services.message_queue.avro_models.io.renku.events.v1.user_removed import UserRemoved
from renku_data_services.message_queue.avro_models.io.renku.events.v1.user_updated import UserUpdated
from renku_data_services.message_queue.db import EventRepository
from renku_data_services.message_queue.interface import IMessageQueue
from renku_data_services.message_queue.redis_queue import dispatch_message
from renku_data_services.namespace.db import GroupRepository
from renku_data_services.users.kc_api import IKeycloakAPI
from renku_data_services.users.models import KeycloakAdminEvent, UserInfo, UserInfoUpdate, Secret
from renku_data_services.users.orm import LastKeycloakEventTimestamp, SecretORM, UserORM
from renku_data_services.utils.core import with_db_transaction


class UserRepo:
    """An adapter for accessing users from the database."""

    def __init__(
        self,
        session_maker: Callable[..., AsyncSession],
        message_queue: IMessageQueue,
        event_repo: EventRepository,
        group_repo: GroupRepository,
    ):
        self.session_maker = session_maker
        self._users_sync = UsersSync(self.session_maker, message_queue, event_repo, group_repo)

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
    async def get_users(self, requested_by: APIUser, email: str | None = None) -> list[UserInfo]:
        """Get users from the database."""
        if not email and not requested_by.is_admin:
            raise errors.Unauthorized(message="Non-admin users cannot list all users.")
        users = await self._get_users(email)

        is_api_user_missing = not any([requested_by.id == user.id for user in users])

        if not email and is_api_user_missing:
            api_user_info = await self._add_api_user(requested_by)
            users.append(api_user_info)
        return users

    async def _get_users(self, email: str | None = None) -> list[UserInfo]:
        async with self.session_maker() as session:
            stmt = select(UserORM)
            if email:
                stmt = stmt.where(UserORM.email == email)
            res = await session.execute(stmt)
            orms = res.scalars().all()
            return [orm.dump() for orm in orms]

    @only_authenticated
    async def get_or_cerate_user_secret_key(self, requested_by:APIUser, user_id: str):
        """Get a users secret key, or create it if it doesn't exist"""
        
        async with self.session_maker() as session, session.begin():

def create_user_added_message(result: UserInfo, **_) -> UserAdded:
    """Transform user to message queue message."""
    return UserAdded(id=result.id, firstName=result.first_name, lastName=result.last_name, email=result.email)


def create_user_updated_message(result: UserInfo, **_) -> UserUpdated:
    """Transform user to message queue message."""
    return UserUpdated(id=result.id, firstName=result.first_name, lastName=result.last_name, email=result.email)


def create_user_removed_message(result, user_id: str) -> UserRemoved:
    """Transform user removal to message queue message."""
    return UserRemoved(id=user_id)


class UsersSync:
    """Sync users from Keycloak to the database."""

    def __init__(
        self,
        session_maker: Callable[..., AsyncSession],
        message_queue: IMessageQueue,
        event_repo: EventRepository,
        group_repo: GroupRepository,
    ):
        self.session_maker = session_maker
        self.message_queue: IMessageQueue = message_queue
        self.event_repo: EventRepository = event_repo
        self.group_repo = group_repo

    async def _get_user(self, id) -> UserInfo | None:
        """Get a specific user."""
        async with self.session_maker() as session, session.begin():
            stmt = select(UserORM).where(UserORM.keycloak_id == id)
            res = await session.execute(stmt)
            orm = res.scalar_one_or_none()
            return orm.dump() if orm else None

    async def update_or_insert_user(self, user_id: str, **kwargs) -> UserORM:
        """Update a user or insert it if it does not exist."""
        async with self.session_maker() as session, session.begin():
            res = await session.execute(select(UserORM).where(UserORM.keycloak_id == user_id))
            existing_user = res.scalar_one_or_none()
        if existing_user:
            return await self.update_user(user_id=user_id, existing_user=existing_user, **kwargs)
        else:
            return await self.insert_user(user_id=user_id, **kwargs)

    @with_db_transaction
    @dispatch_message(create_user_added_message)
    async def insert_user(self, session: AsyncSession, user_id: str, **kwargs) -> UserInfo:
        """Insert a user."""
        kwargs.pop("keycloak_id", None)
        kwargs.pop("id", None)
        new_user = UserORM(keycloak_id=user_id, **kwargs)
        session.add(new_user)
        await session.flush()
        await self.group_repo.insert_user_namespace(new_user, session, retry_enumerate=5, retry_random=True)
        return new_user.dump()

    @with_db_transaction
    @dispatch_message(create_user_updated_message)
    async def update_user(
        self, session: AsyncSession, user_id: str, existing_user: UserORM | None, **kwargs
    ) -> UserInfo:
        """Update a user."""
        if not existing_user:
            async with self.session_maker() as session, session.begin():
                res = await session.execute(select(UserORM).where(UserORM.keycloak_id == user_id))
                existing_user = res.scalar_one_or_none()
        if not existing_user:
            raise errors.MissingResourceError(message=f"The user with id '{user_id}' cannot be found")

        kwargs.pop("keycloak_id", None)
        kwargs.pop("id", None)
        session.add(existing_user)  # reattach to session
        for field_name, field_value in kwargs.items():
            if getattr(existing_user, field_name, None) != field_value:
                setattr(existing_user, field_name, field_value)
        return existing_user.dump()

    @with_db_transaction
    @dispatch_message(create_user_removed_message)
    async def _remove_user(self, session: AsyncSession, user_id: str):
        """Remove a user from the database."""
        logging.info(f"Removing user with ID {user_id}")
        stmt = delete(UserORM).where(UserORM.keycloak_id == user_id)
        await session.execute(stmt)

    async def users_sync(self, kc_api: IKeycloakAPI):
        """Sync all users from Keycloak into the users database."""
        async with self.session_maker() as session, session.begin():
            logging.info("Starting a total user database sync.")
            kc_users = kc_api.get_users()

            async def _do_update(raw_kc_user: dict[str, Any]):
                kc_user = UserInfo.from_kc_user_payload(raw_kc_user)
                logging.info(f"Checking user with Keycloak ID {kc_user.id}")
                db_user = await self._get_user(kc_user.id)
                if db_user != kc_user:
                    logging.info(f"Inserting or updating user {db_user} -> {kc_user}")
                    await self.update_or_insert_user(kc_user.id, **asdict(kc_user))

            # NOTE: If asyncio.gather is used here you quickly exhaust all DB connections
            # or timeout on waiting for available connections
            for user in kc_users:
                await _do_update(user)

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


class UserSecretRepo:
    """An adapter for accessing users secrets."""

    def __init__(
        self,
        session_maker: Callable[..., AsyncSession],
        message_queue: IMessageQueue,
        event_repo: EventRepository,
        group_repo: GroupRepository,
    ):
        self.session_maker = session_maker

    @only_authenticated
    async def get_secrets(self, requested_by: APIUser, user_id: str) -> list[Secret]:
        """Get a specific user secret from the database."""
        if user_id != requested_by.id and not requested_by.is_admin:
            raise errors.Unauthorized(message="Cannot list secrets.")
        async with self.session_maker() as session:
            stmt = select(SecretORM).where(SecretORM.user_id == user_id)
            res = await session.execute(stmt)
            orm = res.scalars().all()
            return [o.dump() for o in orm]

    @only_authenticated
    async def get_secret_by_id(self, requested_by: APIUser, user_id: str, secret_id: str) -> Secret | None:
        """Get a specific user secret from the database."""
        if user_id != requested_by.id and not requested_by.is_admin:
            raise errors.Unauthorized(message="Cannot list secrets.")
        async with self.session_maker() as session:
            stmt = select(SecretORM).where(SecretORM.user_id == user_id).where(SecretORM.id == secret_id)
            res = await session.execute(stmt)
            orm = res.scalar_one_or_none()
            if orm is None:
                return None
            return orm.dump()

    @only_authenticated
    async def insert_secret(self, requested_by: APIUser, user_id: str, secret: Secret) -> Secret | None:
        """Insert a new secret."""
        if user_id != requested_by.id and not requested_by.is_admin:
            raise errors.Unauthorized(message="Cannot create secret.")

        async with self.session_maker() as session, session.begin():
            modification_date = datetime.now(UTC).replace(microsecond=0)
            orm = SecretORM(
                name=secret.name,
                modification_date=modification_date,
                user_id=user_id,
                encrypted_value=secret.encrypted_value,
            )
            session.add(orm)

            try:
                await session.flush()
            except IntegrityError as err:
                if len(err.args) > 0 and "UniqueViolationError" in err.args[0]:
                    raise errors.ValidationError(
                        message="The name for the secret should be unique but it already exists",
                        detail="Please modify the name field and then retry",
                    )
            return orm.dump()

    @only_authenticated
    async def update_secret(
        self, requested_by: APIUser, user_id: str, secret_id: str, encrypted_value: bytes
    ) -> Secret:
        """Update a secret."""
        if user_id != requested_by.id and not requested_by.is_admin:
            raise errors.Unauthorized(message="Cannot update secret.")

        async with self.session_maker() as session, session.begin():
            result = await session.execute(
                select(SecretORM).where(SecretORM.id == secret_id).where(SecretORM.user_id == user_id)
            )
            secret = result.scalar_one_or_none()
            if secret is None:
                raise errors.MissingResourceError(message=f"The secret with id '{secret_id}' cannot be found")

            secret.encrypted_value = encrypted_value
            secret.modification_date = datetime.now(UTC).replace(microsecond=0)
        return secret.dump()

    @only_authenticated
    async def delete_secret(self, requested_by: APIUser, user_id: str, secret_id: str) -> None:
        """Delete a secret."""
        if user_id != requested_by.id and not requested_by.is_admin:
            raise errors.Unauthorized(message="Cannot delete secret.")

        async with self.session_maker() as session, session.begin():
            result = await session.execute(
                select(SecretORM).where(SecretORM.id == secret_id).where(SecretORM.user_id == user_id)
            )
            secret = result.scalar_one_or_none()
            if secret is None:
                return None

            await session.execute(delete(SecretORM).where(SecretORM.id == secret.id))
