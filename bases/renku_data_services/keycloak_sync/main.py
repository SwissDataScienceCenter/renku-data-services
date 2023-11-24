"""Script to synchronize Keycloak and the user database."""
import asyncio
import logging
from dataclasses import asdict
from datetime import datetime, timedelta

from sqlalchemy import NullPool, func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from renku_data_services.keycloak_sync.config import SyncConfig
from renku_data_services.migrations.core import run_migrations_for_app
from renku_data_services.users.models import KeycloakAdminEvent, UserInfo, UserInfoUpdate
from renku_data_services.users.orm import LastKeycloakEventTimestamp, UserORM

logging.basicConfig(level=logging.INFO)


async def main():
    """Synchronize data from Keycloak and the user database."""
    config = SyncConfig.from_env()
    run_migrations_for_app("users")
    engine = create_async_engine(config.async_sqlalchemy_url, poolclass=NullPool)
    async with AsyncSession(engine) as session, session.begin():
        if config.total_user_sync:
            logging.info("Starting a total user database sync.")
            kc_users = config.kc_api.get_users()
            for raw_kc_user in kc_users:
                kc_user = UserInfo.from_kc_user_payload(raw_kc_user)
                db_user = await config.db.get_user(kc_user.id)
                if db_user != kc_user:
                    await config.db.update_or_insert_user(kc_user.id, **asdict(kc_user))
        else:
            res_count = await session.execute(select(func.count()).select_from(UserORM))
            count = res_count.scalar() or 0
            if count == 0:
                logging.info("No users found in the database, doing a full sync.")
                kc_users = config.kc_api.get_users()
                for raw_kc_user in kc_users:
                    kc_user = UserInfo.from_kc_user_payload(raw_kc_user)
                    await config.db.update_or_insert_user(kc_user.id, **asdict(kc_user))
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
            user_events = config.kc_api.get_user_events(start_date=start_date)
            update_admin_events = config.kc_api.get_admin_events(
                start_date=start_date, event_types=[KeycloakAdminEvent.CREATE, KeycloakAdminEvent.UPDATE]
            )
            delete_admin_events = config.kc_api.get_admin_events(
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
                await config.db.update_or_insert_user(update.user_id, **{update.field_name: update.new_value})
                latest_update_timestamp = update.timestamp_utc
            for deletion in parsed_deletions:
                logging.info(f"Processing deletion event {deletion}")
                await config.db.remove_user(deletion.user_id)
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


if __name__ == "__main__":
    asyncio.run(main())
