"""Message queue implementation for redis streams."""

import copy
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import wraps
from typing import Concatenate, ParamSpec, Protocol, TypeVar

from dataclasses_avroschema.schema_generator import AvroModel
from sqlalchemy.ext.asyncio import AsyncSession

from renku_data_services.errors import errors
from renku_data_services.message_queue import AmbiguousEvent
from renku_data_services.message_queue.config import RedisConfig
from renku_data_services.message_queue.converters import EventConverter
from renku_data_services.message_queue.db import EventRepository
from renku_data_services.message_queue.interface import IMessageQueue
from renku_data_services.message_queue.models import Event


class WithMessageQueue(Protocol):
    """The protcol required for a class to send messages to a message queue."""

    @property
    def event_repo(self) -> EventRepository:
        """Returns the event repository."""
        ...


_P = ParamSpec("_P")
_T = TypeVar("_T")
_WithMessageQueue = TypeVar("_WithMessageQueue", bound=WithMessageQueue)


def dispatch_message(
    event_type: type[AvroModel] | AmbiguousEvent,
) -> Callable[
    [Callable[Concatenate[_WithMessageQueue, _P], Awaitable[_T]]],
    Callable[Concatenate[_WithMessageQueue, _P], Awaitable[_T]],
]:
    """Sends a message on the message queue.

    The transform method is called with the arguments and result of the wrapped method. It is responsible for
    creating the message type to dispatch. The message is sent based on the return type of the transform method.
    This wrapper takes care of guaranteed at-least-once delivery of messages by using a backup 'events' table that
    stores messages for redelivery shold sending fail. For this to work correctly, the messages need to be stored
    in the events table in the same database transaction as the metadata update that they are related to.
    All this is to ensure that downstream consumers are kept up to date. They are expected to handle multiple
    delivery of the same message correctly.
    This code addresses these potential error cases:
    - Data being persisted in our database but no message being sent due to errors/restarts of the service at the
      wrong time.
    - Redis not being available.
    Downstream consumers are expected to handle the following:
    - The same message being delivered more than once. Deduplication can be done due to the message ids being
      the identical.
    - Messages being delivered out of order. This should be super rare, e.g. a user edits a project, message delivery
      fails duf to redis being down, the user then deletes the project and message delivery works. Then the first
      message is delivered again and this works, meaning downstream the project deletion arrives before the project
      update. Order can be maintained due to the timestamps in the messages.
    """

    def decorator(
        f: Callable[Concatenate[_WithMessageQueue, _P], Awaitable[_T]],
    ) -> Callable[Concatenate[_WithMessageQueue, _P], Awaitable[_T]]:
        @wraps(f)
        async def message_wrapper(self: _WithMessageQueue, *args: _P.args, **kwargs: _P.kwargs):
            session = kwargs.get("session")
            if not isinstance(session, AsyncSession):
                raise errors.ProgrammingError(
                    message="The decorator that populates the message queue expects a valid database session "
                    f"in the keyword arguments instead it got {type(session)}."
                )
            result = await f(self, *args, **kwargs)
            if result is None:
                return result  # type: ignore[unreachable]
            events = EventConverter.to_events(result, event_type)

            for event in events:
                event_id = await self.event_repo.store_event(session, event)

                try:
                    await self.event_repo.message_queue.send_message(event)
                except Exception as err:
                    logging.warning(
                        f"Could not insert event message to redis queue because of {err} "
                        "events have been added to postgres, will attempt to send them later."
                    )
                    return result
                await self.event_repo.delete_event(event_id)
            return result

        return message_wrapper

    return decorator


@dataclass
class RedisQueue(IMessageQueue):
    """Redis streams queue implementation."""

    config: RedisConfig

    async def send_message(self, event: Event) -> None:
        """Send a message on a channel."""
        message = copy.copy(event.serialize())

        await self.config.redis_connection.xadd(event.queue, message)
