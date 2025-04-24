"""Adapters for project database classes."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from renku_data_services import errors
from renku_data_services.message_queue import orm as schemas
from renku_data_services.message_queue.interface import IMessageQueue
from renku_data_services.message_queue.models import Event, Reprovisioning

logger = logging.getLogger(__name__)


class EventRepository:
    """Repository for events."""

    def __init__(
        self,
        session_maker: Callable[..., AsyncSession],
        message_queue: IMessageQueue,
    ) -> None:
        self.session_maker = session_maker
        self.message_queue: IMessageQueue = message_queue

    async def get_pending_events(self) -> list[schemas.EventORM]:
        """Get all pending events."""
        async with self.session_maker() as session:
            stmt = select(schemas.EventORM).order_by(schemas.EventORM.timestamp_utc)
            events_orm = await session.scalars(stmt)
            return list(events_orm.all())

    async def send_pending_events(self) -> None:
        """Get all pending events and send them.

        We lock rows that get sent and keep sending until there are no more events.
        """
        n_total_events = 0

        while True:
            async with self.session_maker() as session, session.begin():
                stmt = (
                    select(schemas.EventORM)
                    # lock retrieved rows, skip already locked ones, to deal with concurrency
                    .with_for_update(skip_locked=True)
                    .limit(100)
                    .order_by(schemas.EventORM.timestamp_utc)
                )
                result = await session.scalars(stmt)
                events_orm = result.all()

                new_events_count = len(events_orm)
                logger.info(f"Got {new_events_count} events to send to redis")
                if new_events_count == 0:
                    break

                n_total_events += new_events_count

                for event in events_orm:
                    try:
                        await self.message_queue.send_message(event.dump())
                        logger.info(f"Event sent: {event.id}")
                        await session.delete(event)  # this has to be done in the same transaction to not get a deadlock
                        logger.info(f"Event deleted: {event.id}")
                    except Exception as e:
                        logger.warning(f"Couldn't send event {event.id}: {event.payload} on queue {event.queue}: {e}")

        if n_total_events > 0:
            logger.info(f"sent {n_total_events} events to the message queue")

    async def store_event(self, session: AsyncSession | Session, event: Event) -> int:
        """Store an event."""
        event_orm = schemas.EventORM.load(event)
        session.add(event_orm)

        return event_orm.id

    async def delete_event(self, id: int) -> None:
        """Delete an event."""
        async with self.session_maker() as session, session.begin():
            stmt = delete(schemas.EventORM).where(schemas.EventORM.id == id)
            await session.execute(stmt)

    async def delete_all_events(self) -> None:
        """Delete all events. This is only used when testing reprovisioning."""
        async with self.session_maker() as session, session.begin():
            await session.execute(delete(schemas.EventORM))


class ReprovisioningRepository:
    """Repository for Reprovisioning."""

    def __init__(self, session_maker: Callable[..., AsyncSession]) -> None:
        self.session_maker = session_maker

    async def start(self) -> Reprovisioning:
        """Create a new reprovisioning."""
        async with self.session_maker() as session, session.begin():
            active_reprovisioning = await session.scalar(select(schemas.ReprovisioningORM))
            if active_reprovisioning:
                raise errors.ConflictError(message="A reprovisioning is already in progress")

            reprovisioning_orm = schemas.ReprovisioningORM(start_date=datetime.now(UTC).replace(microsecond=0))
            session.add(reprovisioning_orm)

            return reprovisioning_orm.dump()

    async def get_active_reprovisioning(self) -> Reprovisioning | None:
        """Get current reprovisioning."""
        async with self.session_maker() as session:
            active_reprovisioning = await session.scalar(select(schemas.ReprovisioningORM))
            return active_reprovisioning.dump() if active_reprovisioning else None

    async def stop(self) -> None:
        """Stop current reprovisioning."""
        async with self.session_maker() as session, session.begin():
            await session.execute(delete(schemas.ReprovisioningORM))
