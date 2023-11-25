"""Base models for API specifications."""
from pydantic import BaseModel, Extra, Field


class BaseAPISpec(BaseModel):
    """Base API specification."""

    class Config:
        """Enables orm mode for pydantic."""

        from_attributes = True
