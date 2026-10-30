"""Base models for API specifications."""

from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator
from ulid import ULID

from renku_data_services.base_models.validation import reject_null_if_not_nullable


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

    @field_validator("*", mode="before", check_fields=False)
    @classmethod
    def reject_null(cls, value: Any, info: ValidationInfo) -> Any:
        """Reject null for optional fields that are not nullable."""
        return reject_null_if_not_nullable(cls, value, info)
