"""Base models for API specifications."""

from pydantic import BaseModel, Field
from ulid import ULID


class BaseAPISpec(BaseModel):
    """Base API specification."""

    class Config:
        """Enables orm mode for pydantic."""

        from_attributes = True


class RepositoryFilter(BaseAPISpec):
    """The schema for the query parameters used to filter resource classes."""

    class Config:
        """Configuration."""

        extra = "ignore"

    project_id: str = Field()


class RepositoryFilterV2(BaseAPISpec):
    """The schema for the query parameters used to filter resource classes."""

    class Config:
        """Configuration."""

        extra = "ignore"

    project_id: ULID
