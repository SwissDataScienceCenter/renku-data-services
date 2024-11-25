"""Base models for API specifications."""

from pydantic import BaseModel, field_validator
from ulid import ULID


class BaseAPISpec(BaseModel):
    """Base API specification."""

    class Config:
        """Enables orm mode for pydantic."""

        from_attributes = True
        # NOTE: By default the pydantic library does not use python for regex but a rust crate
        # this rust crate does not support lookahead regex syntax but we need it in this component
        regex_engine = "python-re"

    @field_validator("id", "template_id", mode="before", check_fields=False)
    @classmethod
    def serialize_ulid_fields(cls, value: str | ULID | None) -> str | None:
        """Custom serializer that can handle ULIDs."""
        return None if value is None else str(value)
