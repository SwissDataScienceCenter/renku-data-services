"""Protocol for metrics service."""

from typing import Protocol

from renku_data_services.base_models.core import APIUser


class MetricsService(Protocol):
    """Protocol for sending product metrics."""

    async def session_started(self, user: APIUser, metadata: dict[str, str | int]) -> None:
        """Send session start event to metrics."""
        ...

    async def session_resumed(self, user: APIUser, metadata: dict[str, str | int]) -> None:
        """Send session resumed event to metrics."""
        ...

    async def session_hibernated(self, user: APIUser, metadata: dict[str, str | int]) -> None:
        """Send session paused event to metrics."""
        ...

    async def session_stopped(self, user: APIUser, metadata: dict[str, str | int]) -> None:
        """Send session stopped event to metrics."""
        ...

    async def session_launcher_created(
        self, user: APIUser, environment_kind: str, environment_image_source: str
    ) -> None:
        """Send session launcher created event to metrics."""
        ...

    async def project_created(self, user: APIUser) -> None:
        """Send project created event to metrics."""
        ...

    async def code_repo_linked_to_project(self, user: APIUser) -> None:
        """Send code linked to project event to metrics."""
        ...

    async def data_connector_created(self, user: APIUser) -> None:
        """Send data connector created event to metrics."""
        ...

    async def data_connector_linked(self, user: APIUser) -> None:
        """Send data connector linked event to metrics."""
        ...

    async def project_member_added(self, user: APIUser) -> None:
        """Send project member added event to metrics."""
        ...

    async def group_created(self, user: APIUser) -> None:
        """Send group created event to metrics."""
        ...

    async def group_member_added(self, user: APIUser) -> None:
        """Send group member added event to metrics."""
        ...

    async def search_queried(self, user: APIUser) -> None:
        """Send search queried event to metrics."""
        ...
