"""Protocol for metrics service."""

from typing import Protocol

from renku_data_services.base_models.core import APIUser


class MetricsService(Protocol):
    """Protocol for sending product metrics."""

    async def session_started(self, user: APIUser, metadata: dict[str, str | int]) -> None:
        """Send session start event to metrics."""
        ...

    async def session_resumed(self, user: APIUser) -> None:
        """Send session resumed event to metrics."""
        ...

    async def session_paused(self, user: APIUser) -> None:
        """Send session paused event to metrics."""
        ...

    async def session_stopped(self, user: APIUser) -> None:
        """Send session stopped event to metrics."""
        ...
