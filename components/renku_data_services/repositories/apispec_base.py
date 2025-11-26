"""Base models for API specifications."""

from typing import Any

from pydantic import BaseModel, Field, HttpUrl, field_validator
from ulid import ULID


class BaseAPISpec(BaseModel):
    """Base API specification."""

    class Config:
        """Enables orm mode for pydantic."""

        from_attributes = True
        # NOTE: By default the pydantic library does not use python for regex but a rust crate
        # this rust crate does not support lookahead regex syntax but we need it in this component
        regex_engine = "python-re"

    @field_validator("*", mode="before", check_fields=False)
    @classmethod
    def serialize_connection_id(cls, value: Any) -> Any:
        """Custom serializer that can handle ULIDs."""
        if isinstance(value, ULID):
            return str(value)
        return value


class RepositoryParams(BaseAPISpec):
    """The schema for the path parameters used in the repository requests."""

    class Config:
        """Configuration."""

        extra = "ignore"

    repository_url: HttpUrl = Field(...)
