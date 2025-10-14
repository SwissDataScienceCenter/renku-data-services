"""Protocol for metrics service."""

from enum import StrEnum
from typing import Protocol

from renku_data_services.base_models.core import APIUser
from renku_data_services.users.models import UserInfo


class MetricsEvent(StrEnum):
    """The different types of metrics events."""

    code_repo_linked_to_project = "code_repo_linked_to_project"
    data_connector_created = "data_connector_created"
    data_connector_linked = "data_connector_linked"
    group_created = "group_created"
    group_member_added = "group_member_added"
    identify_user = "identify_user"
    project_created = "project_created"
    project_member_added = "project_member_added"
    search_queried = "search_queried"
    session_hibernated = "session_hibernated"
    session_launcher_created = "session_launcher_created"
    session_resumed = "session_resumed"
    session_started = "session_started"
    session_stopped = "session_stopped"
    user_requested_session_launch = "user_requested_session_launch"
    user_requested_session_resume = "user_requested_session_resume"


type MetricsMetadata = dict[str, str | int | bool]


class MetricsService(Protocol):
    """Protocol for sending product metrics."""

    async def identify_user(self, user: UserInfo, metadata: MetricsMetadata) -> None:
        """Send a user's identity to metrics."""
        ...

    async def session_started(self, user: APIUser, metadata: MetricsMetadata) -> None:
        """Send session start event to metrics."""
        ...

    async def session_resumed(self, user: APIUser, metadata: MetricsMetadata) -> None:
        """Send session resumed event to metrics."""
        ...

    async def session_hibernated(self, user: APIUser, metadata: MetricsMetadata) -> None:
        """Send session paused event to metrics."""
        ...

    async def session_stopped(self, user: APIUser, metadata: MetricsMetadata) -> None:
        """Send session stopped event to metrics."""
        ...

    async def session_launcher_created(
        self, user: APIUser, environment_kind: str, environment_image_source: str
    ) -> None:
        """Send session launcher created event to metrics."""
        ...

    async def project_created(self, user: APIUser, metadata: MetricsMetadata) -> None:
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

    async def user_requested_session_launch(self, user: APIUser, metadata: MetricsMetadata) -> None:
        """Send event about user requesting session launch."""
        ...

    async def user_requested_session_resume(self, user: APIUser, metadata: MetricsMetadata) -> None:
        """Send event about user requesting session resume."""
        ...


class ProjectCreationType(StrEnum):
    """The different types of project creation metrics."""

    new = "new"
    migrated = "migrated"
    copied = "copied"
