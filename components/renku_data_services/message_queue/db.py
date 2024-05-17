"""Adapters for project database classes."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from sanic.log import logger
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from renku_data_services.message_queue import orm as schemas
from renku_data_services.message_queue.interface import IMessageQueue


class EventRepository:
    """Repository for events."""

    def __init__(
        self,
        session_maker: Callable[..., AsyncSession],
        message_queue: IMessageQueue,
    ):
        self.session_maker = session_maker  # type: ignore[call-overload]
        self.message_queue: IMessageQueue = message_queue

    async def get_pending_events(self) -> list[schemas.EventORM]:
        """Get all pending events."""
        async with self.session_maker() as session:
            stmt = select(schemas.EventORM)
            result = await session.execute(stmt)
            events_orm = result.scalars().all()
            return list(events_orm)

    async def send_pending_events(self) -> None:
        """Get all pending events and send them."""
        logger.info("sending pending events.")

        async with self.session_maker() as session:
            # we only consider events older than 5 seconds so we don't accidentally interfere with an ongoing operation
            stmt = select(schemas.EventORM).order_by(schemas.EventORM.timestamp_utc)
            result = await session.scalars(stmt)
            events_orm = result.all()

            num_events = len(events_orm)
            if num_events == 0:
                logger.info("no events to send")
                return
            for event in events_orm:
                try:
                    await self.message_queue.send_message(event.queue, event.payload)  # type:ignore

                    await self.delete_event(event.id)
                except Exception as e:
                    logger.warning(f"couldn't send event {event.payload} on queue {event.queue}: {e}")

        logger.info(f"sent {num_events} events")

    async def store_event(self, session: AsyncSession, queue: str, message: dict[str, Any]) -> int:
        """Store an event."""
        event = schemas.EventORM(datetime.utcnow(), queue, message)
        session.add(event)

        return event.id

    async def delete_event(self, id: int):
        """Delete an event."""
        async with self.session_maker() as session, session.begin():
            stmt = delete(schemas.EventORM).where(schemas.EventORM.id == id)
            await session.execute(stmt)
