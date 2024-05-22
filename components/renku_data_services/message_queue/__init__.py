"""Message queue classes."""

from enum import StrEnum


class AmbiguousEvent(StrEnum):
    """Indicates that a single operation in the data service can result in multiple different events being generated."""

    PROJECT_MEMBERSHIP_CHANGED: str = "project_membership_changed"
    GROUP_MEMBERSHIP_CHANGED: str = "group_membership_changed"
    UPDATE_OR_INSERT_USER: str = "update_or_insert_user"
    INSERT_USER_NAMESPACE: str = "insert_user_namespace"
