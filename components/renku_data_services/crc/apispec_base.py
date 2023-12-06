"""Base models for API specifications."""
from pydantic import BaseModel, Field


class BaseAPISpec(BaseModel):
    """Base API specification."""

    class Config:
        """Enables orm mode for pydantic."""

        from_attributes = True


class ResourceClassesFilter(BaseAPISpec):
    """The schema for the query parameters used to filter resource classes."""

    class Config:
        """Configuration."""

        extra = "ignore"

    cpu: float = Field(ge=0.0, default=0.0)
    memory: int = Field(ge=0, default=0)
    gpu: int = Field(ge=0, default=0)
    max_storage: int = Field(ge=0, default=0)
