"""Adapters for project database classes."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

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

    async def _get_pending_events(self, older_than: timedelta = timedelta(0)) -> list[schemas.EventORM]:
        """Get all pending events."""
        async with self.session_maker() as session:
            now = datetime.now(UTC).replace(tzinfo=None)
            stmt = select(schemas.EventORM).where(schemas.EventORM.timestamp_utc < now - older_than)
            events_orm = await session.scalars(stmt)
            return list(events_orm.all())

    async def send_pending_events(self) -> None:
        """Get all pending events and resend them.

        This is to ensure that an event is sent at least once.
        """
        logger.info("resending missed events.")

        # we only consider events older than 5 seconds so we don't accidentally interfere with an ongoing operation
        events_orm = await self._get_pending_events(older_than=timedelta(seconds=5))

        num_events = len(events_orm)
        if num_events == 0:
            logger.info("no missed events to send")
            return
        for event in events_orm:
            try:
                await self.message_queue.send_message(event.dump())
                await self.delete_event(event.id)
            except Exception as e:
                logger.warning(f"couldn't resend event {event.payload} on queue {event.queue}: {e}")

        logger.info(f"resent {num_events} events")

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
