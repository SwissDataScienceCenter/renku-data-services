"""Models for persisted logs."""

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
class InsertLogsResult:
    """Result of inserting a log stream in the database."""

    log_count: int
    last_timestamp: int
