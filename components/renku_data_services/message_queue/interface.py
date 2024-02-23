"""Interface for message queue client."""

from datetime import datetime
from typing import Protocol

from renku_data_services.project.apispec import Visibility
from renku_data_services.project.orm import ProjectRepositoryORM


class IMessageQueue(Protocol):
    """Interface for message queue client."""

    async def project_created(
        self,
        name: str,
        slug: str,
        visibility: Visibility,
        id: str,
        repositories: list[ProjectRepositoryORM],
        description: str | None,
        creation_date: datetime,
        created_by: str,
        members: list[str],
    ):
        """Event for when a new project is created."""
        ...
