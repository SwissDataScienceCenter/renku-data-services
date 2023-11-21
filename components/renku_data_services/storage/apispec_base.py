"""Base models for API specifications."""
from pydantic import BaseModel, Extra, Field


class BaseAPISpec(BaseModel):
    """Base API specification."""

    class Config:
        """Enables orm mode for pydantic."""

        from_attributes = True


class RepositoryFilter(BaseAPISpec):
    """The schema for the query parameters used to filter resource classes."""

    class Config:
        """Configuration."""

        extra = Extra.ignore

    project_id: str = Field()


class SchemaValidationArguments(BaseAPISpec):
    """The schema for the query parameters used rclone schema validation."""

    class Config:
        """Configuration."""

        extra = Extra.ignore

    test_connection: bool = Field(default=False)
