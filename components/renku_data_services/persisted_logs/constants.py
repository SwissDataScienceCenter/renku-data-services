"""Constants for persisted logs."""

from typing import Final

PERSISTED_LOGS_SESSIONS_LABEL_KEY: Final[str] = "app"
"""The loki label key to select session logs streams."""

PERSISTED_LOGS_SESSIONS_LABEL_VALUE: Final[str] = "AmaltheaSession"
"""The loki label value to select session logs streams."""

PERSISTED_LOGS_NAMESPACE_LABEL_KEY: Final[str] = "namespace"
"""The loki label key to select logs streams from a specific kubernetes namespace."""
