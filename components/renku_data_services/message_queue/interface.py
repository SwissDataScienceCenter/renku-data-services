"""Interface for message queue client."""

from typing import Any, Protocol


class IMessageQueue(Protocol):
    """Interface for message queue client."""

    async def send_message(
        self,
        channel: str,
        message: dict[str, Any],
    ):
        """Send a message on a channel."""
        ...
