"""Base models for API specifications."""

from pydantic import BaseModel, field_validator
from ulid import ULID


class BaseAPISpec(BaseModel):
    """Base API specification."""

    class Config:
        """Enables orm mode for pydantic."""

        from_attributes = True

    @field_validator("storage_id", mode="before", check_fields=False)
    @classmethod
    def serialize_storage_id(cls, storage_id: str | ULID) -> str:
        """Custom serializer that can handle ULIDs."""
        return str(storage_id)

    @field_validator("secret_id", mode="before", check_fields=False)
    @classmethod
    def secret_storage_id(cls, secret_id: str | ULID) -> str:
        """Custom serializer that can handle ULIDs."""
        return str(secret_id)
