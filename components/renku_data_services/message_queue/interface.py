"""Interface for message queue client."""
from typing import Protocol

from renku_data_services.message_queue.models import ProjectCreatedEvent


class IMessageQueue(Protocol):
    """Interface for message queue client."""

    def project_created(self, event: ProjectCreatedEvent):
        """Event for when a new project is created."""
        ...
