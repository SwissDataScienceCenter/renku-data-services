"""Base models for API specifications."""

from pathlib import PurePosixPath
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator, model_validator
from ulid import ULID

from renku_data_services.session import models


class BaseAPISpec(BaseModel):
    """Base API specification."""

    # Enables orm mode for pydantic.
    model_config = ConfigDict(
        from_attributes=True,
    )

    @model_validator(mode="before")
    @classmethod
    def serialize_ulid(cls, value: Any) -> Any:
        """Recursively convert ULID instances to strings in raw input."""

        def _convert(v: Any) -> Any:
            if isinstance(v, ULID):
                return str(v)
            if isinstance(v, dict):
                return {k: _convert(val) for k, val in v.items()}
            if isinstance(v, list):
                return [_convert(item) for item in v]
            return v

        return _convert(value)

    @field_validator("id", mode="before", check_fields=False)
    @classmethod
    def serialize_id(cls, v: ULID) -> str:
        """Custom serializer that can handle ULIDs for id."""
        return str(v)

    @field_validator("project_id", mode="before", check_fields=False)
    @classmethod
    def serialize_project_id(cls, project_id: str | ULID) -> str:
        """Custom serializer that can handle ULIDs."""
        return str(project_id)

    @field_validator("environment_id", mode="before", check_fields=False)
    @classmethod
    def serialize_environment_id(cls, environment_id: str | ULID | None) -> str | None:
        """Custom serializer that can handle the environment kind."""
        if environment_id is None:
            return None
        return str(environment_id)

    @field_validator("environment_kind", mode="before", check_fields=False)
    @classmethod
    def serialize_environment_kind(cls, environment_kind: models.EnvironmentKind | str) -> str:
        """Custom serializer that can handle ULIDs."""
        if isinstance(environment_kind, models.EnvironmentKind):
            return environment_kind.value
        return environment_kind

    @field_validator("working_directory", "mount_directory", check_fields=False, mode="before")
    @classmethod
    def convert_path_to_string(cls, val: str | PurePosixPath) -> str:
        """Converts the python path to a regular string when pydantic deserializes."""
        if isinstance(val, PurePosixPath):
            return val.as_posix()
        return val
