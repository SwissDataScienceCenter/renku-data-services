"""Models for notifications."""

from dataclasses import dataclass
from datetime import datetime

from ulid import ULID


@dataclass(frozen=True, eq=True, kw_only=True)
class Alert:
    """An alert stored in the database."""

    id: ULID
    user_id: str
    event_type: str
    session_name: str | None = None
    title: str
    message: str
    creation_date: datetime
    resolved_date: datetime | None = None


@dataclass(frozen=True, eq=True, kw_only=True)
class UnsavedAlert:
    """An alert that has not been persisted yet."""

    user_id: str
    event_type: str
    session_name: str | None = None
    title: str
    message: str


@dataclass(frozen=True, kw_only=True)
class AlertPatch:
    """A patch for an existing alert."""

    resolved: bool | None = None
