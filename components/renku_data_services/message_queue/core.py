"""Business logic for message queue and events."""

import json
from collections.abc import AsyncGenerator, Callable

from dataclasses_avroschema.schema_generator import AvroModel
from sanic.log import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from renku_data_services.authz.authz import Authz, ResourceType
from renku_data_services.base_models import APIUser
from renku_data_services.message_queue import events
from renku_data_services.message_queue.avro_models.io.renku.events import v2
from renku_data_services.message_queue.converters import EventConverter, make_event
from renku_data_services.message_queue.db import ReprovisioningRepository
from renku_data_services.message_queue.models import Event, Reprovisioning
from renku_data_services.message_queue.orm import EventORM
from renku_data_services.namespace.db import GroupRepository
from renku_data_services.project.db import ProjectRepository
from renku_data_services.users.db import UserRepo


async def reprovision(
    session_maker: Callable[..., AsyncSession],
    requested_by: APIUser,
    reprovisioning: Reprovisioning,
    reprovisioning_repo: ReprovisioningRepository,
    user_repo: UserRepo,
    group_repo: GroupRepository,
    project_repo: ProjectRepository,
    authz: Authz,
) -> None:
    """Create and send various data service events required for reprovisioning the message queue."""
    logger.info(f"Starting reprovisioning with ID {reprovisioning.id}")

    async def process_events(
        records: AsyncGenerator, event_type: type[AvroModel] | type[events.AmbiguousEvent]
    ) -> None:
        """Create and store an event."""
        count = 0

        async for entity in records:
            events = EventConverter.to_events(entity, event_type=event_type)
            await store_event(events[0])
            count += 1

        logger.info(f"Reprovisioned {count} {event_type.__name__} events")

    async def store_event(event: Event) -> None:
        """Store an event in the temporary events table."""
        event_orm = EventORM.load(event)

        await session.execute(
            text(
                """
                INSERT INTO events_temp (queue, payload, timestamp_utc)
                VALUES
                (:queue, :payload ::JSONB, :timestamp_utc)
                """
            ).bindparams(
                queue=event_orm.queue,
                payload=json.dumps(event_orm.payload),
                timestamp_utc=event_orm.timestamp_utc,
            )
        )

    try:
        async with session_maker() as session, session.begin():
            # NOTE: The table should be deleted at the end of the transaction. This is just a safety-net around
            # (possible) bugs that a reprovisioning might not get cleared.
            await session.execute(text("DROP TABLE IF EXISTS events_temp"))
            # NOTE: The temporary table will be deleted once the transaction gets committed/aborted.
            await session.execute(
                text(
                    """
                    CREATE TEMPORARY TABLE events_temp ON COMMIT DROP
                    AS
                    SELECT queue, payload, timestamp_utc FROM events.events WHERE FALSE WITH NO DATA
                    """
                )
            )

            start_event = make_event(
                message_type="reprovisioning.started", payload=v2.ReprovisioningStarted(id=str(reprovisioning.id))
            )
            await store_event(start_event)

            logger.info("Reprovisioning users")
            all_users = user_repo.get_all_users(requested_by=requested_by)
            await process_events(all_users, v2.UserAdded)

            all_groups = group_repo.get_all_groups(requested_by=requested_by)
            await process_events(all_groups, v2.GroupAdded)

            all_groups_members = authz.get_all_members(ResourceType.group)
            await process_events(all_groups_members, v2.GroupMemberAdded)

            all_projects = project_repo.get_all_projects(requested_by=requested_by)
            await process_events(all_projects, v2.ProjectCreated)

            all_projects_members = authz.get_all_members(ResourceType.project)
            await process_events(all_projects_members, v2.ProjectMemberAdded)

            finish_event = make_event(
                message_type="reprovisioning.finished", payload=v2.ReprovisioningFinished(id=str(reprovisioning.id))
            )
            await store_event(finish_event)

            await session.execute(
                text(
                    """
                    INSERT INTO events.events (queue, payload, timestamp_utc)
                    SELECT queue, payload, timestamp_utc
                    FROM events_temp
                    """
                )
            )
    except Exception as e:
        logger.exception(f"An error occurred during reprovisioning with ID {reprovisioning.id}: {e}")
    else:
        logger.info(f"Reprovisioning with ID {reprovisioning.id} is successfully finished")
    finally:
        await reprovisioning_repo.stop()
