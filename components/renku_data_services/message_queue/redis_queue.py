"""Message queue implementation for redis streams."""
from renku_data_services.message_queue.avro_models.io.renku.events.v1 import ProjectCreated
from renku_data_services.message_queue.interface import IMessageQueue


class RedisQueue(IMessageQueue):
    """Redis streams queue implementation."""

    def project_created(self, event: ProjectCreated):
        """Event for when a new project is created."""
        ...
