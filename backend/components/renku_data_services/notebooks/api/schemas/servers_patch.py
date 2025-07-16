"""Server PATCH schemas."""

from enum import Enum
from typing import Self

from marshmallow import EXCLUDE, Schema, fields, validate

from renku_data_services.notebooks import apispec


class PatchServerStatusEnum(Enum):
    """Possible values when patching a server."""

    Running = "running"
    Hibernated = "hibernated"

    @classmethod
    def list(cls) -> list[str]:
        """Get list of enum values."""
        return [e.value for e in cls]

    @classmethod
    def from_api_state(cls, state: apispec.State) -> Self:
        """Get the state from the apispec enum."""
        if state.value == cls.Running.value:
            return cls("running")
        return cls("hibernated")


class PatchServerRequest(Schema):
    """Simple Enum for server status."""

    class Meta:
        """Marshmallow schema configuration."""

        # passing unknown params does not error, but the params are ignored
        unknown = EXCLUDE

    state = fields.String(required=False, validate=validate.OneOf(PatchServerStatusEnum.list()))
    resource_class_id = fields.Int(required=False, validate=lambda x: x > 0)
