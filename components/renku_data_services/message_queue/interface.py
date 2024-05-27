"""Interface for message queue client."""

from typing import Protocol

from renku_data_services.message_queue.models import Event


class IMessageQueue(Protocol):
    """Interface for message queue client."""

    async def send_message(self, event: Event):
        """Send a message on a channel."""
        ...
