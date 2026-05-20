"""Base models for API specifications."""

from enum import Enum
from pathlib import PurePosixPath
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator
from ulid import ULID

from renku_data_services.session import models


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

    @field_validator("project_id", mode="before", check_fields=False)
    @classmethod
    def serialize_project_id(cls, project_id: str | ULID) -> str:
        """Custom serializer that can handle ULIDs."""
        return str(project_id)

    @field_validator("environment_id", mode="before", check_fields=False)
    @classmethod
    def serialize_environment_id(cls, environment_id: str | ULID | None) -> str | None:
        """Custom serializer that can handle ULIDs."""
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

    @field_validator("launcher_type", mode="before", check_fields=False)
    @classmethod
    def convert_to_api_launcher_type(cls, lt: Any) -> Any:
        """Convert the model launcher type into a valid value when serializing."""
        from renku_data_services.session import apispec

        return validate_enum_value(lt, "launcher_type", apispec.LauncherType)


def validate_enum_value(lt: Any, field_name: str, enum_class: type[Enum]) -> Enum | str:
    """Validate a enum value."""
    all_values = [e.value for e in enum_class]
    if isinstance(lt, enum_class):
        return lt
    if isinstance(lt, str):
        try:
            return enum_class(lt)
        except ValueError as e:
            raise ValueError(f"Invalid {field_name}: {lt}. Expect one of {all_values}") from e

    raise ValueError(f"{field_name} must be one of: {all_values}")
