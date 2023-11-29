"""Base models for API specifications."""
from pydantic import BaseModel, Field


class BaseAPISpec(BaseModel):
    """Base API specification."""

    class Config:
        """Enables orm mode for pydantic."""

        from_attributes = True


class PinnedProjectFilter(BaseAPISpec):
    """The schema for the query parameters used to filter pinned projects."""

    class Config:
        """Configuration."""

        extra = "ignore"

    project_slug: str = Field(default="")
