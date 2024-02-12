"""Message queue implementation for redis streams."""
from renku_data_services.message_queue.interface import IMessageQueue
from renku_data_services.message_queue.models import ProjectCreatedEvent


class RedisQueue(IMessageQueue):
    """Redis streams queue implementation."""

    def project_created(self, event: ProjectCreatedEvent):
        """Event for when a new project is created."""
        ...
