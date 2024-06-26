"""Adapters for project database classes."""

from __future__ import annotations

from collections.abc import Callable

from sanic.log import logger
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from renku_data_services.message_queue import orm as schemas
from renku_data_services.message_queue.interface import IMessageQueue
from renku_data_services.message_queue.models import Event


class EventRepository:
    """Repository for events."""

    def __init__(
        self,
        session_maker: Callable[..., AsyncSession],
        message_queue: IMessageQueue,
    ) -> None:
        self.session_maker = session_maker
        self.message_queue: IMessageQueue = message_queue

    async def _get_pending_events(self) -> list[schemas.EventORM]:
        """Get all pending events."""
        async with self.session_maker() as session:
            stmt = select(schemas.EventORM)
            events_orm = await session.scalars(stmt)
            return list(events_orm.all())

    async def send_pending_events(self) -> None:
        """Get all pending events and send them.

        We lock rows that get sent and keep sending until there are no more events.
        """
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
                if new_events_count == 0:
                    break

                for event in events_orm:
                    try:
                        await self.message_queue.send_message(event.dump())

                        await session.delete(event)  # this has to be done in the same transaction to not get a deadlock
                    except Exception as e:
                        logger.warning(f"couldn't send event {event.payload} on queue {event.queue}: {e}")

                logger.info(f"sent {new_events_count} events")

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
