"""Base models for API specifications."""

from pydantic import BaseModel, ConfigDict


class BaseAPISpec(BaseModel):
    """Base API specification."""

    model_config = ConfigDict(
        # Enables orm mode for pydantic."""
        from_attributes=True,
    )
