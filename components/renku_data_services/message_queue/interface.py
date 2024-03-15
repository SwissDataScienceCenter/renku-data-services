"""Interface for message queue client."""

from typing import Protocol


class IMessageQueue(Protocol):
    """Interface for message queue client."""

    async def send_message(
        self,
        channel: str,
        message: dict[bytes | memoryview | str | int | float, bytes | memoryview | str | int | float],
    ):
        """Send a message on a channel."""
        ...
