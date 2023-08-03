"""Data models for query parameters used in requests."""
from pydantic import Extra, Field

from renku_data_services.storage_schemas.base import BaseAPISpec


class RepositoryFilter(BaseAPISpec):
    """The schema for the query parameters used to filter resource classes."""

    class Config:
        """Configuration."""

        extra = Extra.ignore

    git_url: str = Field()
