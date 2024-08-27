"""Base models for API specifications."""

from pathlib import PurePosixPath

from pydantic import BaseModel, field_validator
from ulid import ULID


class BaseAPISpec(BaseModel):
    """Base API specification."""

    class Config:
        """Enables orm mode for pydantic."""

        from_attributes = True

    @field_validator("id", "project_id", mode="before", check_fields=False)
    @classmethod
    def serialize_id(cls, id: str | ULID) -> str:
        """Custom serializer that can handle ULIDs."""
        return str(id)

    @field_validator("working_directory", "mount_directory", check_fields=False, mode="before")
    @classmethod
    def convert_path_to_string(cls, val: str | PurePosixPath) -> str:
        """Converts the python path to a regular string when pydantic deserializes."""
        if isinstance(val, PurePosixPath):
            return val.as_posix()
        return val