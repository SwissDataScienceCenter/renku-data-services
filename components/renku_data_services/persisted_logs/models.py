"""Models for persisted logs."""

from collections.abc import Sequence
from dataclasses import dataclass

from ulid import ULID


@dataclass(eq=True, frozen=True, kw_only=True)
class UnsavedLogLine:
    """Represents an unsaved log line."""

    id: str
    """The ID of the log line.

    This is used to de-duplicate log lines.
    """

    user_id: str
    run_id: ULID
    session_uid: str | None
    launcher_id: ULID
    submission_id: str | None
    container: str
    timestamp: int
    log_line: str


@dataclass(eq=True, frozen=True, kw_only=True)
class SessionRun:
    """The continuous execution span of a session."""

    id: ULID
    session_uid: str | None
    launcher_id: ULID
    submission_id: str | None


@dataclass(eq=True, frozen=True, kw_only=True)
class LogLine:
    """A single log line."""

    timestamp: int
    log_line: str


@dataclass(eq=True, frozen=True, kw_only=True)
class ContainerLogs:
    """Logs of a single container."""

    container: str
    logs: Sequence[LogLine]


@dataclass(eq=True, frozen=True, kw_only=True)
class PersistedSessionLogs:
    """Result of getting session logs from the database."""

    run: SessionRun
    logs: Sequence[ContainerLogs]


@dataclass(eq=True, frozen=True, kw_only=True)
class InsertLogsResult:
    """Result of inserting a log stream in the database."""

    log_count: int
    last_timestamp: int


@dataclass(eq=True, frozen=True, kw_only=True)
class UnsavedBuildLogLine:
    """Represents an unsaved image build log line."""

    id: str
    """The ID of the log line.

    This is used to de-duplicate log lines.
    """

    build_id: ULID
    container: str
    timestamp: int
    log_line: str
