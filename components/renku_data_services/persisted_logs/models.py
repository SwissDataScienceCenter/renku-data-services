"""Models for persisted logs."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ulid import ULID


@dataclass(eq=True, frozen=True, kw_only=True)
class UnsavedLogLine:
    """Represents an unsaved log line."""

    id: str
    """The ID of the log line.

    This is used to de-duplicate log lines.
    """

    run_id: ULID
    user_id: str
    launch_id: str
    launcher_id: ULID
    submission_id: str | None
    container: str
    timestamp: int
    log_line: str


@dataclass(eq=True, frozen=True, kw_only=True)
class SessionRun:
    """The continuous execution span of a session."""

    id: ULID
    user_id: str
    launch_id: str
    launcher_id: ULID
    submission_id: str | None


@dataclass(eq=True, frozen=True, kw_only=True)
class LogLine:
    """A single log line."""

    timestamp: int
    log_line: str


type SessionRunLogs = Mapping[str, Sequence[LogLine]]
"""Logs of a session run, organized by pod container."""


@dataclass(eq=True, frozen=True, kw_only=True)
class GetSessionLogsResult:
    """Result of getting session logs from the database."""

    run: SessionRun
    logs: SessionRunLogs


@dataclass(eq=True, frozen=True, kw_only=True)
class InsertLogsResult:
    """Result of inserting a log stream in the database."""

    log_count: int
    last_timestamp: int
