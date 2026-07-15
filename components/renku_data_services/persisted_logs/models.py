"""Models for persisted logs."""

from dataclasses import dataclass

from ulid import ULID


@dataclass
class UnsavedLogLine:
    """Represents an unsaved log line."""

    id: str
    """The ID of the log line.

    This is used to de-duplicate log lines.
    """

    run_id: str
    user_id: str
    launch_id: str
    launcher_id: ULID
    submission_id: str | None
    container: str
    timestamp: int
    log_line: str
