"""Base models for API specifications."""

from pydantic import BaseModel, field_validator
from ulid import ULID

from renku_data_services.session import models


class BaseAPISpec(BaseModel):
    """Base API specification."""

    class Config:
        """Enables orm mode for pydantic."""

        from_attributes = True

    @field_validator("project_id", mode="before", check_fields=False)
    @classmethod
    def serialize_id(cls, project_id: str | ULID) -> str:
        """Custom serializer that can handle ULIDs."""
        return str(project_id)

    @field_validator("environment_kind", mode="before", check_fields=False)
    @classmethod
    def serialize_environment_kind(cls, environment_kind: models.EnvironmentKind | str) -> str:
        """Custom serializer that can handle ULIDs."""
        if isinstance(environment_kind, models.EnvironmentKind):
            return environment_kind.value
        return environment_kind
