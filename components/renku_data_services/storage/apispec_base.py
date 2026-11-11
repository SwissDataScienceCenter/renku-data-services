"""Base models for API specifications."""

from pathlib import PurePosixPath
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator
from ulid import ULID


class BaseAPISpec(BaseModel):
    """Base API specification."""

    model_config = ConfigDict(
        # Enables orm mode for pydantic."""
        from_attributes=True,
    )

    @field_validator("*", mode="before", check_fields=False)
    @classmethod
    def serialize_ulid(cls, value: Any) -> Any:
        """Handle ULIDs."""
        if isinstance(value, ULID):
            return str(value)
        return value

    @field_validator("mount_path", mode="before", check_fields=False)
    @classmethod
    def serialize_mount_path(cls, value: Any) -> Any:
        """Handle mount path serialization."""
        if isinstance(value, PurePosixPath):
            return value.as_posix()
        return value
