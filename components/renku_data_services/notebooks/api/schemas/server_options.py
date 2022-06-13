from marshmallow import Schema, fields, ValidationError

from ...config import SERVER_OPTIONS_DEFAULTS, SERVER_OPTIONS_UI
from .custom_fields import (
    CpuField,
    GpuField,
    MemoryField,
)


def get_validator(field_name, server_options_ui, server_options_defaults):
    def _validate(value):
        if field_name in server_options_ui:
            if server_options_ui[field_name].get("allow_any_value", False):
                return True
            elif "value_range" in server_options_ui[field_name]:
                within_range = (
                    value >= server_options_ui[field_name]["value_range"]["min"]
                    and value <= server_options_ui[field_name]["value_range"]["max"]
                )
                if not within_range:
                    raise ValidationError(
                        f"Provided {field_name} value not within allowed range of "
                        f"{server_options_ui[field_name]['value_range']['min']} and "
                        f"{server_options_ui[field_name]['value_range']['max']}."
                    )
            else:
                if value not in server_options_ui[field_name]["options"]:
                    raise ValidationError(
                        f"Provided {field_name} value is not in the allowed options "
                        f"{server_options_ui[field_name]['options']}"
                    )
        else:
            if value != server_options_defaults[field_name]:
                raise ValidationError(
                    f"Provided {field_name} value does not match the allowed value of "
                    f"{server_options_defaults[field_name]}"
                )

    return _validate


class LaunchNotebookRequestServerOptions(Schema):
    defaultUrl = fields.Str(
        required=False,
        missing=SERVER_OPTIONS_DEFAULTS["defaultUrl"],
    )
    cpu_request = CpuField(
        required=False,
        missing=SERVER_OPTIONS_DEFAULTS["cpu_request"],
        validate=get_validator(
            "cpu_request", SERVER_OPTIONS_UI, SERVER_OPTIONS_DEFAULTS
        ),
    )
    mem_request = MemoryField(
        required=False,
        missing=SERVER_OPTIONS_DEFAULTS["mem_request"],
        validate=get_validator(
            "mem_request", SERVER_OPTIONS_UI, SERVER_OPTIONS_DEFAULTS
        ),
    )
    disk_request = MemoryField(
        required=False,
        missing=SERVER_OPTIONS_DEFAULTS["disk_request"],
        validate=get_validator(
            "disk_request", SERVER_OPTIONS_UI, SERVER_OPTIONS_DEFAULTS
        ),
    )
    lfs_auto_fetch = fields.Bool(
        required=False, missing=SERVER_OPTIONS_DEFAULTS["lfs_auto_fetch"]
    )
    gpu_request = GpuField(
        required=False,
        missing=SERVER_OPTIONS_DEFAULTS["gpu_request"],
        validate=get_validator(
            "gpu_request", SERVER_OPTIONS_UI, SERVER_OPTIONS_DEFAULTS
        ),
    )
