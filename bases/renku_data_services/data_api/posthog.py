"""Posthog implementation for metrics server."""

import hashlib

from renku_data_services.base_models.core import APIUser
from renku_data_services.base_models.metrics import MetricsService


class PosthogService(MetricsService):
    """Posthog metrics service."""

    enabled: bool

    def __init__(self, enabled: bool, api_key: str, host: str) -> None:
        """Create new instance."""
        self.enabled = enabled
        if self.enabled:
            from posthog import Posthog

            self._posthog = Posthog(api_key=api_key, host=host)

    def _anonymize_user_id(self, user: APIUser) -> str:
        """Anonymize a user id."""
        return hashlib.md5(user.id.encode("utf-8"), usedforsecurity=False).hexdigest() if user.id else "anonymous"

    async def session_started(self, user: APIUser, metadata: dict[str, str | int]) -> None:
        """Send session started event to posthog."""
        if not self.enabled:
            return
        metadata["authenticated"] = user.is_authenticated
        self._posthog.capture(distinct_id=self._anonymize_user_id(user), event="session_started", properties=metadata)

    async def session_resumed(self, user: APIUser, metadata: dict[str, str | int]) -> None:
        """Send session resumed event to metrics."""
        if not self.enabled:
            return
        self._posthog.capture(distinct_id=self._anonymize_user_id(user), event="session_resumed", properties=metadata)

    async def session_hibernated(self, user: APIUser, metadata: dict[str, str | int]) -> None:
        """Send session paused event to metrics."""
        if not self.enabled:
            return
        self._posthog.capture(
            distinct_id=self._anonymize_user_id(user), event="session_hibernated", properties=metadata
        )

    async def session_stopped(self, user: APIUser, metadata: dict[str, str | int]) -> None:
        """Send session stopped event to metrics."""
        if not self.enabled:
            return
        metadata["authenticated"] = user.is_authenticated
        self._posthog.capture(
            distinct_id=self._anonymize_user_id(user),
            event="session_stopped",
            properties=metadata,
        )

    async def session_launcher_created(
        self, user: APIUser, environment_kind: str, environment_image_source: str
    ) -> None:
        """Send session launcher created event to metrics."""
        if not self.enabled:
            return
        self._posthog.capture(
            distinct_id=self._anonymize_user_id(user),
            event="session_launcher_created",
            properties={"environment_kind": environment_kind, "environment_image_source": environment_image_source},
        )

    async def project_created(self, user: APIUser) -> None:
        """Send project created event to metrics."""
        if not self.enabled:
            return
        self._posthog.capture(distinct_id=self._anonymize_user_id(user), event="project_created")

    async def code_repo_linked_to_project(self, user: APIUser) -> None:
        """Send code linked to project event to metrics."""
        if not self.enabled:
            return
        self._posthog.capture(distinct_id=self._anonymize_user_id(user), event="code_repo_linked_to_project")

    async def data_connector_created(self, user: APIUser) -> None:
        """Send data connector created event to metrics."""
        if not self.enabled:
            return
        self._posthog.capture(distinct_id=self._anonymize_user_id(user), event="data_connector_created")

    async def data_connector_linked(self, user: APIUser) -> None:
        """Send data connector linked event to metrics."""
        if not self.enabled:
            return
        self._posthog.capture(distinct_id=self._anonymize_user_id(user), event="data_connector_linked")

    async def project_member_added(self, user: APIUser) -> None:
        """Send project member added event to metrics."""
        if not self.enabled:
            return
        self._posthog.capture(distinct_id=self._anonymize_user_id(user), event="project_member_added")

    async def group_created(self, user: APIUser) -> None:
        """Send group created event to metrics."""
        if not self.enabled:
            return
        self._posthog.capture(distinct_id=self._anonymize_user_id(user), event="group_created")

    async def group_member_added(self, user: APIUser) -> None:
        """Send group member added event to metrics."""
        if not self.enabled:
            return
        self._posthog.capture(distinct_id=self._anonymize_user_id(user), event="group_member_added")

    async def search_queried(self, user: APIUser) -> None:
        """Send search queried event to metrics."""
        if not self.enabled:
            return
        self._posthog.capture(
            distinct_id=self._anonymize_user_id(user),
            event="search_queried",
            properties={"authenticated": user.is_authenticated},
        )
