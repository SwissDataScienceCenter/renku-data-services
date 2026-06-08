"""Models for Renku apps."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from ulid import ULID

from renku_data_services.renku_apps import apispec


class AppStatus(StrEnum):
    """The status of an app."""

    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"
    HIBERNATED = "hibernated"


@dataclass(frozen=True, eq=True, kw_only=True)
class App:
    """An App."""

    name: str
    launcher_id: ULID
    project_id: ULID
    status: AppStatus
    url: str | None = None
    started: datetime | None = None
    image: str | None = None

    def as_apispec(self) -> apispec.AppResponse:
        """Convert the app to an API response model."""
        return apispec.AppResponse(
            name=self.name,
            launcher_id=str(self.launcher_id),
            status=apispec.AppStatus(self.status.value),
            url=self.url,
            project_id=str(self.project_id),
            started=self.started,
            image=self.image,
        )


@dataclass(frozen=True, kw_only=True)
class AppRuntimeState:
    """Runtime state of an app deployment, as observed in the cluster.

    Carries the primitives that the K8s adapter extracts from a Knative Service
    so that domain logic can compose an App without depending on K8s types.
    The ready_status field holds the raw Kubernetes Ready-condition status value
    ("True", "False", "Unknown", or None if the condition is absent).
    """

    name: str
    launcher_id: ULID
    project_id: ULID
    ready_status: str | None
    is_hibernated: bool
    image: str | None
    url: str | None
    started_at: datetime | None
