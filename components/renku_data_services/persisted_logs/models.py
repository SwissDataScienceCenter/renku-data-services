"""Models for persisted logs."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ulid import ULID


@dataclass(eq=True, frozen=True, kw_only=True)
class SessionRun:
    """The continuous execution span of a session."""

    id: ULID
    user_id: str
    session_uid: str | None
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
class PersistedSessionLogs:
    """Result of getting session logs from the database."""

    run: SessionRun
    logs: SessionRunLogs
