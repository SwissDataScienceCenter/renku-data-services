"""Base models for API specifications."""

from pydantic import BaseModel, Field


class BaseAPISpec(BaseModel):
    """Base API specification."""

    class Config:
        """Enables orm mode for pydantic."""

        from_attributes = True
        # NOTE: By default the pydantic library does not use python for regex but a rust crate
        # this rust crate does not support lookahead regex syntax but we need it in this component
        regex_engine = "python-re"


class GetProjectsParams(BaseAPISpec):
    """The schema for the query parameters used in the get projects request."""

    class Config:
        """Configuration."""

        extra = "ignore"

    namespace: str = Field(default="")
