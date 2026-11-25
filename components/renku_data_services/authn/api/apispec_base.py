"""Base models for API specifications."""

from pydantic import BaseModel, ConfigDict


class BaseAPISpec(BaseModel):
    """Base API specification."""

    # Enables orm mode for pydantic.
    model_config = ConfigDict(from_attributes=True)
