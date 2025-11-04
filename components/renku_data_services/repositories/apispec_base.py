"""Base models for API specifications."""

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

    @field_validator("id", mode="before", check_fields=False)
    @classmethod
    def serialize_connection_id(cls, id: str | ULID | None) -> str | None:
        """Custom serializer that can handle ULIDs."""
        if id is None:
            return None
        return str(id)


class RepositoryParams(BaseAPISpec):
    """The schema for the path parameters used in the repository requests."""

    class Config:
        """Configuration."""

        extra = "ignore"

    repository_url: HttpUrl = Field(...)
