"""Protocol for metrics service."""

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha1
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


@dataclass(eq=True, frozen=True, kw_only=True)
class UserIdentity:
    """Represents a user's identity."""

    user_id: str
    email: str | None
    first_name: str | None
    last_name: str | None
    username: str | None

    def hash(self) -> str:
        """Returns a hash of the identity."""
        digest = sha1(usedforsecurity=False)
        digest.update(f"user_id={self.user_id}".encode())
        digest.update(f"email={self.email}".encode())
        digest.update(f"first_name={self.first_name}".encode())
        digest.update(f"last_name={self.last_name}".encode())
        digest.update(f"username={self.username}".encode())
        return digest.hexdigest()

    def to_dict(self) -> dict[str, str]:
        """Returns a dictionary representation of the identity."""
        data = dict(user_id=self.user_id)
        if self.email:
            data["email"] = self.email
        if self.first_name:
            data["first_name"] = self.first_name
        if self.last_name:
            data["last_name"] = self.last_name
        if self.username:
            data["username"] = self.username
        return data


class MetricsService(Protocol):
    """Protocol for sending product metrics."""

    async def identify_user(
        self, user: UserInfo, existing_identity_hash: str | None, metadata: MetricsMetadata
    ) -> UserIdentity | None:
        """Send a user's identity to metrics.

        Returns an instance of UserIdentity if the the event has actually been saved and None otherwise.
        """
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
