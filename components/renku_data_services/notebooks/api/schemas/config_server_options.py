from marshmallow import (
    Schema,
    validate,
    fields,
)

from .custom_fields import (
    CpuField,
    GpuField,
    MemoryField,
)


class BaseServerOptionsChoice(Schema):
    order = fields.Int(required=True, validate=lambda x: x >= 1)
    displayName = fields.Str(required=True)
    type = fields.Str(required=True, validate=validate.OneOf(["enum", "boolean"]))


class CpuServerOptionsChoice(BaseServerOptionsChoice):
    default = CpuField(required=True)
    options = fields.List(CpuField(required=True))
    value_range = fields.Nested(
        Schema.from_dict(
            {
                "min": CpuField(required=True),
                "max": CpuField(required=True),
                # NOTE: type is unused, left in for backwards compatibility with older Helm charts
                "type": fields.Str(required=False),
            }
        ),
        required=False,
    )
    allow_any_value = fields.Bool(
        required=False, load_default=False, dump_default=False
    )


class GpuServerOptionsChoice(BaseServerOptionsChoice):
    default = GpuField(required=True)
    options = fields.List(GpuField(required=True))
    value_range = fields.Nested(
        Schema.from_dict(
            {
                "min": GpuField(required=True),
                "max": GpuField(required=True),
                # NOTE: type is unused, left in for backwards compatibility with older Helm charts
                "type": fields.Str(required=False),
            }
        ),
        required=False,
    )
    allow_any_value = fields.Bool(
        required=False, load_default=False, dump_default=False
    )


class MemoryServerOptionsChoice(BaseServerOptionsChoice):
    default = MemoryField(required=True)
    options = fields.List(MemoryField(required=True))
    value_range = fields.Nested(
        Schema.from_dict(
            {
                "min": MemoryField(required=True),
                "max": MemoryField(required=True),
                # NOTE: type is unused, left in for backwards compatibility with older Helm charts
                "type": fields.Str(required=False),
            }
        ),
        required=False,
    )
    allow_any_value = fields.Bool(
        required=False, load_default=False, dump_default=False
    )


class StringServerOptionsChoice(BaseServerOptionsChoice):
    default = fields.Str(required=True)
    options = fields.List(fields.Str(required=True))


class BoolServerOptionsChoice(BaseServerOptionsChoice):
    default = fields.Bool(required=True)


class ServerOptionsChoices(Schema):
    """Used to deserialize (load) the server options choices from the Helm values file."""

    defaultUrl = fields.Nested(StringServerOptionsChoice, required=False)
    cpu_request = fields.Nested(CpuServerOptionsChoice, required=False)
    mem_request = fields.Nested(MemoryServerOptionsChoice, required=False)
    disk_request = fields.Nested(MemoryServerOptionsChoice, required=False)
    lfs_auto_fetch = fields.Nested(BoolServerOptionsChoice, required=False)
    gpu_request = fields.Nested(GpuServerOptionsChoice, required=False)


class ServerOptionsDefaults(Schema):
    """Used to deserialize (load) the server options defaults from the Helm values file."""

    defaultUrl = fields.Str(required=True)
    cpu_request = CpuField(required=True)
    mem_request = MemoryField(required=True)
    disk_request = MemoryField(required=True)
    lfs_auto_fetch = fields.Bool(required=True)
    gpu_request = GpuField(required=True)
