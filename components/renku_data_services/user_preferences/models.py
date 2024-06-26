"""Models for user preferences."""

from typing import Optional

from pydantic import BaseModel, Field


class PinnedProjects(BaseModel):
    """Pinned projects model."""

    project_slugs: Optional[list[str]] = None

    @classmethod
    def from_dict(cls, data: dict) -> "PinnedProjects":
        """Create model from a dict object."""
        return cls(project_slugs=data.get("project_slugs"))


class UserPreferences(BaseModel):
    """User preferences model."""

    user_id: str = Field(min_length=3)
    pinned_projects: PinnedProjects
