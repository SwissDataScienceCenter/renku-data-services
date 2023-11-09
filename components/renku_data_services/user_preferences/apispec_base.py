"""Base models for API specifications."""
from pydantic import BaseModel, Extra, Field


class BaseAPISpec(BaseModel):
    """Base API specification."""

    class Config:
        """Enables orm mode for pydantic."""

        from_attributes = True


class PinnedProjectFilter(BaseAPISpec):
    """The schema for the query parameters used to filter pinned projects."""

    class Config:
        """Configuration."""

        extra = Extra.ignore

    project_slug: str | None = Field()
