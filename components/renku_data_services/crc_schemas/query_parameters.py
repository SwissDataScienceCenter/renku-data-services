"""Data models for query parameters used in requests."""
from pydantic import Extra, Field
from renku_data_services.crc_schemas.base import BaseAPISpec


class ResourceClassesFilter(BaseAPISpec):
    """The schema for the query parameters used to filter resource classes."""

    class Config:
        """Configuration."""

        extra = Extra.ignore

    cpu: float = Field(ge=0.0, default=0.0)
    memory: int = Field(ge=0, default=0)
    gpu: int = Field(ge=0, default=0)
    max_storage: int = Field(ge=0, default=0)
