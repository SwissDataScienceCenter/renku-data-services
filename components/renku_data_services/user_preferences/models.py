"""Models for user preferences."""

from datetime import datetime
from hashlib import md5
from typing import List, MutableSet

from pydantic import BaseModel, Field, field_validator


class PinnedProjects(BaseModel):
    """Pinned projects model."""

    project_slugs: List[str] | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "PinnedProjects":
        """Create model from a dict object."""
        return cls(project_slugs=data.get("project_slugs"))

    @field_validator("project_slugs")
    @classmethod
    def pinned_projects_are_unique(cls, project_slugs: List[str] | None) -> List[str] | None:
        """Validates that pinned projects are unique."""
        seen: MutableSet[str] = set()
        if project_slugs is None:
            return None
        project_slugs = [(seen.add(project), project)[1] for project in project_slugs if project not in seen]
        return project_slugs


class UserPreferences(BaseModel):
    """User preferences model."""

    user_id: str = Field(min_length=3)
    pinned_projects: PinnedProjects
    created_at: datetime | None = Field(default=None)
    updated_at: datetime | None = Field(default=None)

    @property
    def etag(self) -> str | None:
        """Entity tag value for this user preferences object."""
        if self.updated_at is None:
            return None
        return md5(self.updated_at.isoformat().encode(), usedforsecurity=False).hexdigest().upper()
