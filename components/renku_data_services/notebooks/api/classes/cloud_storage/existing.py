"""Cloud storage."""

from dataclasses import dataclass


@dataclass
class ExistingCloudStorage:
    """Cloud storage for a session."""

    remote: str
    type: str
