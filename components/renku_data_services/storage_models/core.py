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

    @classmethod
    def from_dict(cls, data: dict) -> "CloudStorage":
        """Create the model from a plain dictionary."""
        return cls(
            git_url=data["git_url"],
            storage_id=data.get("storage_id"),
            configuration=data["configuration"],
            storage_type=data["configuration"].get("type"),
        )

    @classmethod
    def from_url(cls, storage_url: str, git_url: str) -> "CloudStorage":
        """Get Cloud Storage/rclone config from a storage URL."""
        raise NotImplementedError()
