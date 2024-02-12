"""Interface for message queue client."""
from typing import Protocol

from renku_data_services.message_queue.avro_models.io.renku.v1.project_created import ProjectCreated


class IMessageQueue(Protocol):
    """Interface for message queue client."""

    def project_created(self, event: ProjectCreated):
        """Event for when a new project is created."""
        ...
