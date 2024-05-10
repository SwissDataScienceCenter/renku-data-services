"""Message queue classes."""

from enum import StrEnum


class AmbiguousEvent(StrEnum):
    """Indicates that a single operation in the data service can result in multiple different events being generated."""

    PROJECT_MEMBERSHIP_CHANGED: str = "project_membership_changed"
