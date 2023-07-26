"""Models for cloud storage."""


from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, eq=True, kw_only=True)
class CloudStorage:
    """Cloud Storage model."""

    git_url: str
    storage_type: str
    configuration: dict[str, Any]

    storage_id: str | None = None
