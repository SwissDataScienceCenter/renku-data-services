"""Base models for API specifications."""
from pydantic import BaseModel, Extra, Field


class BaseAPISpec(BaseModel):
    """Base API specification."""

    class Config:
        """Enables orm mode for pydantic."""

        from_attributes = True


class ResourceClassesFilter(BaseAPISpec):
    """The schema for the query parameters used to filter users."""

    class Config:
        """Configuration."""

        extra = Extra.ignore

    email: str | None = Field(default=None, description="The email to filter on for exact match.")
