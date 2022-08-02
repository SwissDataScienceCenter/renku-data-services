from marshmallow import Schema, ValidationError, fields

from ...config import config
from .custom_fields import ByteSizeField, CpuField, GpuField


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
        missing=config.server_options.defaults["defaultUrl"],
    )
    cpu_request = CpuField(
        required=False,
        missing=config.server_options.defaults["cpu_request"],
        validate=get_validator(
            "cpu_request",
            config.server_options.ui_choices,
            config.server_options.defaults,
        ),
    )
    mem_request = ByteSizeField(
        required=False,
        missing=config.server_options.defaults["mem_request"],
        validate=get_validator(
            "mem_request",
            config.server_options.ui_choices,
            config.server_options.defaults,
        ),
    )
    disk_request = ByteSizeField(
        required=False,
        missing=config.server_options.defaults["disk_request"],
        validate=get_validator(
            "disk_request",
            config.server_options.ui_choices,
            config.server_options.defaults,
        ),
    )
    lfs_auto_fetch = fields.Bool(
        required=False, missing=config.server_options.defaults["lfs_auto_fetch"]
    )
    gpu_request = GpuField(
        required=False,
        missing=config.server_options.defaults["gpu_request"],
        validate=get_validator(
            "gpu_request",
            config.server_options.ui_choices,
            config.server_options.defaults,
        ),
    )
