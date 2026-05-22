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
