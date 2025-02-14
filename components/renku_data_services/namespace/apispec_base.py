"""Base models for API specifications."""

import pydantic
from pydantic import BaseModel, field_validator
from ulid import ULID

# NOTE: We are monkeypatching the regex engine for the root model because
# the datamodel code generator that makes classes from the API spec does not
# support setting this for the root model and by default the root model is using
# the rust regex create which does not support lookahead/behind regexs and we need
# that functionality to parse slugs and prevent certain suffixes in slug names.
pydantic.RootModel.model_config = {"regex_engine": "python-re"}


class BaseAPISpec(BaseModel):
    """Base API specification."""

    class Config:
        """Enables orm mode for pydantic."""

        from_attributes = True
        # NOTE: By default the pydantic library does not use python for regex but a rust crate
        # this rust crate does not support lookahead regex syntax but we need it in this component
        regex_engine = "python-re"

    @field_validator("id", mode="before", check_fields=False)
    @classmethod
    def serialize_id(cls, id: str | ULID) -> str:
        """Custom serializer that can handle ULIDs."""
        return str(id)
