"""Entity tag utility functions."""

from datetime import datetime
from hashlib import md5


def compute_etag_from_timestamp(updated_at: datetime, include_quotes: bool = False) -> str:
    """Computes an entity tag value by hashing the updated_at value."""
    etag = md5(updated_at.isoformat().encode(), usedforsecurity=False).hexdigest().upper()
    if not include_quotes:
        return etag
    return f'"{etag}"'
