"""Posthog implementation for metrics server."""

from posthog import Posthog

from renku_data_services.base_models.core import APIUser
from renku_data_services.base_models.metrics import MetricsService


class PosthogService(MetricsService):
    """Posthog metrics service."""

    _posthog: Posthog
    enabled: bool

    def __init__(self, enabled: bool, api_key: str, host: str) -> None:
        """Create new instance."""
        self.enabled = enabled
        if self.enabled:
            self._posthog = Posthog(api_key=api_key, host=host)

    async def session_started(self, user: APIUser, metadata: dict[str, str | int]) -> None:
        """Send session started event to posthog."""
        if not self.enabled:
            return
        self._posthog.capture(distinct_id=user.id, event="session_started", properties={"requests": metadata})
