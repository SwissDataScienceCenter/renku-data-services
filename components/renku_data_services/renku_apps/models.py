"""Models for Renku apps."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from ulid import ULID


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
