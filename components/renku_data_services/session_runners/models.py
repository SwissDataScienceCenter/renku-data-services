"""Models for session runners."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal

from ulid import ULID


class RunnerStatus(StrEnum):
    """The status of a session runner."""

    never_contacted = "never_contacted"
    """The runner has not performed registration yet."""

    initializing = "initializing"
    """The runner has performed registration but is not yet ready to run sessions."""

    ready = "ready"
    """The runner is ready to run sessions."""

    not_ready = "not_ready"
    """The runner is not ready to run sessions."""


@dataclass(eq=True, frozen=True, kw_only=True)
class UnsavedUserSessionRunner:
    """Represents an unsaved user-scoped session runner."""

    resource_pool_id: int


@dataclass(eq=True, frozen=True, kw_only=True)
class UserSessionRunner(UnsavedUserSessionRunner):
    """Represents a user-scoped session runner."""

    id: ULID
    user_id: str
    resource_pool_id: int
    status: RunnerStatus
    registration_token: str | None = None
    creation_date: datetime
    last_contact: datetime | None


@dataclass(eq=True, frozen=True, kw_only=True)
class UserSessionRunnerPatch:
    """Update to a user-scoped session runner."""

    status: Literal[RunnerStatus.ready] | Literal[RunnerStatus.not_ready]
