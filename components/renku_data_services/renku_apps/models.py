"""Models for apps."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from ulid import ULID


class AppState(StrEnum):
    """The status of an app."""

    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"


@dataclass(frozen=True, eq=True, kw_only=True)
class UnsavedApp:
    """An unsaved app."""

    project_id: ULID
    image: str
    created_by: str
    status: AppState = AppState.PENDING
    url: str


@dataclass(frozen=True, eq=True, kw_only=True)
class App(UnsavedApp):
    """An app stored in the database."""

    id: ULID
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, eq=True, kw_only=True)
class AppPatch:
    """A patch for an existing app."""

    disabled: bool
    image: str | None = None  # remove - will be part of session launcher
