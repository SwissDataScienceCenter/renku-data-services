"""Base models for API specifications."""

from pydantic import BaseModel, Field, HttpUrl


class BaseAPISpec(BaseModel):
    """Base API specification."""

    class Config:
        """Enables orm mode for pydantic."""

        from_attributes = True
        # NOTE: By default the pydantic library does not use python for regex but a rust crate
        # this rust crate does not support lookahead regex syntax but we need it in this component
        regex_engine = "python-re"


class AuthorizeParams(BaseAPISpec):
    """The schema for the query parameters used in the authorize request."""

    class Config:
        """Configuration."""

        extra = "ignore"

    next_url: str = Field(default="")


class CallbackParams(BaseAPISpec):
    """The schema for the query parameters used in the authorize callback request."""

    class Config:
        """Configuration."""

        extra = "ignore"

    state: str = Field(default="")


class RepositoryParams(BaseAPISpec):
    """The schema for the path parameters used in the repository requests."""

    class Config:
        """Configuration."""

        extra = "ignore"

    repository_url: HttpUrl = Field(...)
