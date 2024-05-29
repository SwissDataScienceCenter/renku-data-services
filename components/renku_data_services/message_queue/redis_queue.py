"""Message queue implementation for redis streams."""

import copy
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
    Messages are stored in the database in the same transaction as the changed entities, and are sent by a background
    job to ensure delivery of messages and prevent messages being sent in case of failing transactions or due to
    exceptions.
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
                await self.event_repo.store_event(session, event)
            return result

        return message_wrapper

    return decorator


@dataclass
class RedisQueue(IMessageQueue):
    """Redis streams queue implementation."""

    config: RedisConfig

    async def send_message(self, event: Event):
        """Send a message on a channel."""
        message = copy.copy(event.serialize())

        await self.config.redis_connection.xadd(event.queue, message)
