"""Entity tag utility functions."""

from datetime import datetime
from hashlib import md5
from typing import Any


def compute_etag_from_timestamp(updated_at: datetime) -> str:
    """Computes an entity tag value by hashing the updated_at value."""
    etag = md5(updated_at.isoformat().encode(), usedforsecurity=False).hexdigest().upper()
    return f'"{etag}"'


def compute_etag_from_fields(updated_at: datetime, *args: Any) -> str:
    """Computes an entity tag value by hashing the field values.

    By convention, the first field should be `updated_at`.
    """
    values: list[Any] = [updated_at]
    values.extend(arg for arg in args)
    to_hash = "-".join(_get_hashable_string(value) for value in values)
    etag = md5(to_hash.encode(), usedforsecurity=False).hexdigest().upper()
    return f'"{etag}"'


def _get_hashable_string(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return f"{value}"
