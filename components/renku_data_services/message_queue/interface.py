"""Interface for message queue client."""

from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol

from renku_data_services.errors.errors import BaseError
from renku_data_services.project.apispec import Visibility
from renku_data_services.project.orm import ProjectRepositoryORM

if TYPE_CHECKING:
    from renku_data_services.message_queue.db import EventRepository


class MessageContext:
    """Contextmanager to make safe messaging easier."""

    _repo: "EventRepository | None"

    def __init__(self, queue: "IMessageQueue", queue_name: str, message: dict[str, Any]) -> None:
        """Create a new message context."""
        self.queue = queue
        self.queue_name = queue_name
        self._persisted = False
        self.message = message

    async def __aenter__(self):
        """Contextmanager enter function."""
        return self

    async def persist(self, repo: "EventRepository"):
        """Persist the event to the database."""
        self._repo = repo
        self.event_id = await self._repo.store_event("project.created", self.message)
        self._persisted = True

    async def __aexit__(self, exc_type, exc, tb):
        """Contextmanager exit function."""
        if exc_type is not None:
            return
        if not self._persisted or not self._repo:
            raise BaseError(
                message="Messages have to be persisted by calling `persist` on this context before the context exits."
            )
        await self.queue.send_message(self.queue_name, self.message)  # type:ignore
        await self._repo.delete_event(self.event_id)


class IMessageQueue(Protocol):
    """Interface for message queue client."""

    def project_created_message(
        self,
        name: str,
        slug: str,
        visibility: Visibility,
        id: str,
        repositories: list[ProjectRepositoryORM],
        description: str | None,
        creation_date: datetime,
        created_by: str,
    ) -> MessageContext:
        """Event for when a new project is created."""
        ...

    async def send_message(
        self,
        channel: str,
        message: dict[bytes | memoryview | str | int | float, bytes | memoryview | str | int | float],
    ):
        """Send a message on a channel."""
        ...
