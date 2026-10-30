"""Base models for API specifications."""

from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator, model_validator
from ulid import ULID

from renku_data_services.base_models.validation import validate_request_data


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

    @model_validator(mode="before")
    @classmethod
    def validate_request(cls, data: Any, info: ValidationInfo) -> Any:
        """Stricter validation of request data, see validate_request_data."""
        return validate_request_data(cls, data, info)
