"""Database adapters and helpers for users."""

import logging
import secrets
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from renku_data_services.authz.authz import Authz, AuthzOperation, ResourceType
from renku_data_services.base_api.auth import APIUser, only_authenticated
from renku_data_services.errors import errors
from renku_data_services.message_queue import AmbiguousEvent
from renku_data_services.message_queue.avro_models.io.renku.events import v2 as avro_schema_v2
from renku_data_services.message_queue.db import EventRepository
from renku_data_services.message_queue.interface import IMessageQueue
from renku_data_services.message_queue.redis_queue import dispatch_message
from renku_data_services.namespace.db import GroupRepository
from renku_data_services.users.kc_api import IKeycloakAPI
from renku_data_services.users.models import (
    KeycloakAdminEvent,
    UserInfo,
    UserInfoUpdate,
    UserWithNamespace,
    UserWithNamespaceUpdate,
)
from renku_data_services.users.orm import LastKeycloakEventTimestamp, UserORM
from renku_data_services.utils.core import with_db_transaction
from renku_data_services.utils.cryptography import decrypt_string, encrypt_string


class UserRepo:
    """An adapter for accessing users from the database."""

    def __init__(
        self,
        session_maker: Callable[..., AsyncSession],
        message_queue: IMessageQueue,
        event_repo: EventRepository,
        group_repo: GroupRepository,
        encryption_key: bytes,
        authz: Authz,
    ) -> None:
        self.session_maker = session_maker
        self.encryption_key = encryption_key
        self._users_sync = UsersSync(self.session_maker, message_queue, event_repo, group_repo, authz)

    async def initialize(self, kc_api: IKeycloakAPI) -> None:
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
            payload=dict(
                first_name=user.first_name,
                last_name=user.last_name,
                email=user.email,
            ),
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
    async def get_or_create_user_secret_key(self, requested_by: APIUser) -> str:
        """Get a user's secret encryption key or create it if it doesn't exist."""

        async with self.session_maker() as session, session.begin():
            stmt = select(UserORM).where(UserORM.keycloak_id == requested_by.id)
            user = await session.scalar(stmt)
            if not user:
                raise errors.MissingResourceError(message=f"User with id {requested_by.id} not found")
            if user.secret_key is not None:
                return decrypt_string(self.encryption_key, user.keycloak_id, user.secret_key)
            # create a new secret key
            secret_key = secrets.token_urlsafe(32)
            user.secret_key = encrypt_string(self.encryption_key, user.keycloak_id, secret_key)
            session.add(user)

        return secret_key


class UsersSync:
    """Sync users from Keycloak to the database."""

    def __init__(
        self,
        session_maker: Callable[..., AsyncSession],
        message_queue: IMessageQueue,
        event_repo: EventRepository,
        group_repo: GroupRepository,
        authz: Authz,
    ) -> None:
        self.session_maker = session_maker
        self.message_queue: IMessageQueue = message_queue
        self.event_repo: EventRepository = event_repo
        self.group_repo = group_repo
        self.authz = authz

    async def _get_user(self, id: str) -> UserInfo | None:
        """Get a specific user."""
        async with self.session_maker() as session, session.begin():
            stmt = select(UserORM).where(UserORM.keycloak_id == id)
            res = await session.execute(stmt)
            orm = res.scalar_one_or_none()
            return orm.dump() if orm else None

    @with_db_transaction
    @Authz.authz_change(AuthzOperation.update_or_insert, ResourceType.user)
    @dispatch_message(AmbiguousEvent.UPDATE_OR_INSERT_USER)
    async def update_or_insert_user(
        self, user_id: str, payload: dict[str, Any], *, session: AsyncSession | None = None
    ) -> UserWithNamespaceUpdate:
        """Update a user or insert it if it does not exist."""
        if not session:
            raise errors.ProgrammingError(message="A database session is required")
        res = await session.execute(select(UserORM).where(UserORM.keycloak_id == user_id))
        existing_user = res.scalar_one_or_none()
        if existing_user:
            return await self._update_user(session=session, user_id=user_id, existing_user=existing_user, **payload)
        else:
            return await self._insert_user(session=session, user_id=user_id, **payload)

    async def _insert_user(self, session: AsyncSession, user_id: str, **kwargs: Any) -> UserWithNamespaceUpdate:
        """Insert a user."""
        kwargs.pop("keycloak_id", None)
        kwargs.pop("id", None)
        new_user = UserORM(keycloak_id=user_id, **kwargs)
        session.add(new_user)
        await session.flush()
        namespace = await self.group_repo._insert_user_namespace(
            session, new_user, retry_enumerate=5, retry_random=True
        )
        return UserWithNamespaceUpdate(None, UserWithNamespace(new_user.dump(), namespace))

    async def _update_user(
        self, session: AsyncSession, user_id: str, existing_user: UserORM | None, **kwargs: Any
    ) -> UserWithNamespaceUpdate:
        """Update a user."""
        if not existing_user:
            async with self.session_maker() as session, session.begin():
                res = await session.execute(select(UserORM).where(UserORM.keycloak_id == user_id))
                existing_user = res.scalar_one_or_none()
        if not existing_user:
            raise errors.MissingResourceError(message=f"The user with id '{user_id}' cannot be found")
        old_user = existing_user.dump()

        kwargs.pop("keycloak_id", None)
        kwargs.pop("id", None)
        session.add(existing_user)  # reattach to session
        for field_name, field_value in kwargs.items():
            if getattr(existing_user, field_name, None) != field_value:
                setattr(existing_user, field_name, field_value)
        namespace = await self.group_repo._get_user_namespace(user_id)
        if not namespace:
            raise errors.ProgrammingError(
                message=f"Cannot find a user namespace for user {user_id} when updating the user."
            )
        return UserWithNamespaceUpdate(
            UserWithNamespace(old_user, namespace), UserWithNamespace(existing_user.dump(), namespace)
        )

    @with_db_transaction
    @dispatch_message(avro_schema_v2.UserRemoved)
    async def _remove_user(self, user_id: str, *, session: AsyncSession | None = None) -> UserInfo | None:
        """Remove a user from the database."""
        if not session:
            raise errors.ProgrammingError(message="A database session is required")
        logging.info(f"Trying to remove user with ID {user_id}")
        stmt = delete(UserORM).where(UserORM.keycloak_id == user_id).returning(UserORM)
        user = await session.scalar(stmt)
        await self.authz._remove_user_namespace(user_id)
        if not user:
            logging.info(f"User with ID {user_id} was not found.")
            return None
        logging.info(f"User with ID {user_id} was removed from the database.")
        removed_user = user.dump()
        logging.info(f"User namespace with ID {user_id} was removed from the authorization database.")
        return removed_user

    async def users_sync(self, kc_api: IKeycloakAPI) -> None:
        """Sync all users from Keycloak into the users database."""
        logging.info("Starting a total user database sync.")
        kc_users = kc_api.get_users()

        async def _do_update(raw_kc_user: dict[str, Any]) -> None:
            kc_user = UserInfo.from_kc_user_payload(raw_kc_user)
            logging.info(f"Checking user with Keycloak ID {kc_user.id}")
            db_user = await self._get_user(kc_user.id)
            if db_user != kc_user:
                logging.info(f"Inserting or updating user {db_user} -> {kc_user}")
                await self.update_or_insert_user(kc_user.id, asdict(kc_user))

        # NOTE: If asyncio.gather is used here you quickly exhaust all DB connections
        # or timeout on waiting for available connections
        for user in kc_users:
            await _do_update(user)

    async def events_sync(self, kc_api: IKeycloakAPI) -> None:
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
                await self.update_or_insert_user(update.user_id, {update.field_name: update.new_value})
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
