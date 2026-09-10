"""Models for session runners."""

from dataclasses import dataclass
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
class UnsavedSessionRunner:
    """Represents an unsaved session runner."""

    resource_pool_id: int


@dataclass(eq=True, frozen=True, kw_only=True)
class SessionRunner(UnsavedSessionRunner):
    """Represents a session runner."""

    id: ULID
    resource_pool_id: int
    status: RunnerStatus
    # TODO
    registration_token: str | None = None


@dataclass(eq=True, frozen=True, kw_only=True)
class SessionRunnerContactPayload:
    """Payload sent by a session runner."""

    status: Literal[RunnerStatus.ready] | Literal[RunnerStatus.not_ready]
