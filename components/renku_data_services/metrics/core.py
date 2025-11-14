"""Implementation of staging metrics service."""

from renku_data_services.base_models.core import APIUser, AuthenticatedAPIUser
from renku_data_services.base_models.metrics import MetricsEvent, MetricsMetadata, MetricsService, UserIdentity
from renku_data_services.metrics.db import MetricsRepository
from renku_data_services.metrics.utils import anonymize_user_id
from renku_data_services.users.models import UserInfo


class StagingMetricsService(MetricsService):
    """A metrics service implementation that stores events in a staging table.

    This service stores metrics events in a database table, which are then processed by a background task that sends
    them to the actual metrics service.
    """

    def __init__(self, enabled: bool, metrics_repo: MetricsRepository) -> None:
        self.enabled = enabled
        self._metrics_repo = metrics_repo

    async def _store_event(self, event: MetricsEvent, user: APIUser, metadata: MetricsMetadata | None = None) -> bool:
        """Store a metrics event in the staging table."""
        if not self.enabled:
            return False

        anonymous_user_id = anonymize_user_id(user)
        await self._metrics_repo.store_event(event=event.value, anonymous_user_id=anonymous_user_id, metadata=metadata)
        return True

    async def identify_user(
        self, user: UserInfo, existing_identity_hash: str | None, metadata: MetricsMetadata
    ) -> UserIdentity | None:
        """Send a user's identity to metrics.

        Returns an instance of UserIdentity if the the event has actually been saved and None otherwise.
        """

        # Create the result identity
        user_identity = UserIdentity(
            user_id=user.id,
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
            username=user.namespace.latest_slug,
        )

        # Check if the identity is already known
        if user_identity.hash() == existing_identity_hash:
            return None

        # We populate 'metadata' with the user's details.
        metadata.update(user_identity.to_dict())

        # NOTE: Only the 'id' field is used when we call `_store_event()`.
        api_user = AuthenticatedAPIUser(
            id=user.id,
            access_token="",  # nosec B106
            email=user.email or "",
            first_name=user.first_name,
            last_name=user.last_name,
            is_admin=False,
        )
        saved = await self._store_event(MetricsEvent.identify_user, api_user, metadata)
        return user_identity if saved else None

    async def session_started(self, user: APIUser, metadata: MetricsMetadata) -> None:
        """Store session started event in staging table."""
        metadata["authenticated"] = user.is_authenticated
        await self._store_event(MetricsEvent.session_started, user, metadata)

    async def session_resumed(self, user: APIUser, metadata: MetricsMetadata) -> None:
        """Store session resumed event in staging table."""
        await self._store_event(MetricsEvent.session_resumed, user, metadata)

    async def session_hibernated(self, user: APIUser, metadata: MetricsMetadata) -> None:
        """Store session hibernated event in staging table."""
        await self._store_event(MetricsEvent.session_hibernated, user, metadata)

    async def session_stopped(self, user: APIUser, metadata: MetricsMetadata) -> None:
        """Store session stopped event in staging table."""
        metadata["authenticated"] = user.is_authenticated
        await self._store_event(MetricsEvent.session_stopped, user, metadata)

    async def session_launcher_created(
        self, user: APIUser, environment_kind: str, environment_image_source: str
    ) -> None:
        """Store session launcher created event in staging table."""
        await self._store_event(
            MetricsEvent.session_launcher_created,
            user,
            {"environment_kind": environment_kind, "environment_image_source": environment_image_source},
        )

    async def project_created(self, user: APIUser, metadata: MetricsMetadata) -> None:
        """Store project created event in staging table."""
        await self._store_event(MetricsEvent.project_created, user, metadata)

    async def code_repo_linked_to_project(self, user: APIUser) -> None:
        """Store code repo linked to project event in staging table."""
        await self._store_event(MetricsEvent.code_repo_linked_to_project, user)

    async def data_connector_created(self, user: APIUser) -> None:
        """Store data connector created event in staging table."""
        await self._store_event(MetricsEvent.data_connector_created, user)

    async def data_connector_linked(self, user: APIUser) -> None:
        """Store data connector linked event in staging table."""
        await self._store_event(MetricsEvent.data_connector_linked, user)

    async def project_member_added(self, user: APIUser) -> None:
        """Store project member added event in staging table."""
        await self._store_event(MetricsEvent.project_member_added, user)

    async def group_created(self, user: APIUser) -> None:
        """Store group created event in staging table."""
        await self._store_event(MetricsEvent.group_created, user)

    async def group_member_added(self, user: APIUser) -> None:
        """Store group member added event in staging table."""
        await self._store_event(MetricsEvent.group_member_added, user)

    async def search_queried(self, user: APIUser) -> None:
        """Store search queried event in staging table."""
        metadata: MetricsMetadata = {"authenticated": user.is_authenticated}
        await self._store_event(MetricsEvent.search_queried, user, metadata)

    async def user_requested_session_launch(self, user: APIUser, metadata: MetricsMetadata) -> None:
        """Send event about user requesting session launch."""
        await self._store_event(MetricsEvent.user_requested_session_launch, user, metadata)

    async def user_requested_session_resume(self, user: APIUser, metadata: MetricsMetadata) -> None:
        """Send event about user requesting session resume."""
        await self._store_event(MetricsEvent.user_requested_session_resume, user, metadata)
