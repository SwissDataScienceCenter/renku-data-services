"""Models for notifications."""

from dataclasses import dataclass
from datetime import datetime

from ulid import ULID


@dataclass(frozen=True, eq=True, kw_only=True)
class Alert:
    """An alert stored in the database."""

    id: ULID
    user_id: str
    session_name: str | None = None
    title: str
    message: str
    creation_date: datetime


@dataclass(frozen=True, eq=True, kw_only=True)
class UnsavedAlert:
    """An alert that has not been persisted yet."""

    user_id: str
    session_name: str | None = None
    title: str
    message: str
