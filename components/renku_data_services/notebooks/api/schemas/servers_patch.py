"""Server PATCH schemas."""

from enum import Enum

from marshmallow import EXCLUDE, Schema, fields, validate


class PatchServerStatusEnum(Enum):
    """Possible values when patching a server."""

    Running = "running"
    Hibernated = "hibernated"

    @classmethod
    def list(cls):
        """Get list of enum values."""
        return [e.value for e in cls]


class PatchServerRequest(Schema):
    """Simple Enum for server status."""

    class Meta:
        # passing unknown params does not error, but the params are ignored
        unknown = EXCLUDE

    state = fields.String(required=False, validate=validate.OneOf(PatchServerStatusEnum.list()))
    resource_class_id = fields.Int(required=False, validate=lambda x: x > 0)
