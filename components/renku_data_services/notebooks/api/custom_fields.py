from typing import List, Mapping, Any
from marshmallow import fields
from marshmallow.exceptions import ValidationError
import re

from .. import config


class UnionField(fields.Field):
    """
    Field that deserializes multi-type input data to app-level objects.
    Adapted from https://stackoverflow.com/a/64034540
    """

    def __init__(self, val_types: List[fields.Field]):
        self.valid_types = val_types
        super().__init__()

    def _deserialize(
        self, value: Any, attr: str = None, data: Mapping[str, Any] = None, **kwargs
    ):
        """
        _deserialize defines a custom Marshmallow Schema Field that takes in mutli-type
        input data to app-level objects.

        Parameters
        ----------
        value : {Any}
            The value to be deserialized.

        Keyword Parameters
        ----------
        attr : {str} [Optional]
            The attribute/key in data to be deserialized. (default: {None})
        data : {Optional[Mapping[str, Any]]}
            The raw input data passed to the Schema.load. (default: {None})

        Raises
        ----------
        ValidationError : Exception
            Raised when the validation fails on a field or schema.
        """
        errors = []
        # iterate through the types being passed into UnionField via val_types
        for field in self.valid_types:
            try:
                # inherit deserialize method from Fields class
                return field.deserialize(value, attr, data, **kwargs)
            # if error, add error message to error list
            except ValidationError as error:
                errors.append(error.messages)

        raise ValidationError(errors)


def cpu_value_validation(x):
    return x > 0.0 and (x % 1 >= 0.001 or x % 1 == 0.0)


def memory_value_validation(x):
    return re.match(r"^(?:[1-9][0-9]*|[0-9]\.[0-9]*)[EPTGMK][i]{0,1}$", x) is not None


# used in the response from the server_options endpoint that is then
# used by the UI to present a set of options for the user to select when launching a session
serverOptionUICpuValue = fields.Number(validate=cpu_value_validation, required=True)
serverOptionUIDiskValue = fields.String(
    validate=memory_value_validation,
    required=True,
)
serverOptionUIMemoryValue = fields.String(
    validate=memory_value_validation,
    required=True,
)
serverOptionUIUrlValue = fields.Str(
    required=True,
)

# used to validate the server options in the request to launch a notebook
serverOptionRequestCpuValue = fields.Number(
    validate=(
        lambda x: cpu_value_validation(x)
        if "cpu_request" in config.SERVER_OPTIONS_UI.keys()
        else x == config.SERVER_OPTIONS_DEFAULTS["cpu_request"]
    ),
    required=False,
    missing=config.SERVER_OPTIONS_DEFAULTS["cpu_request"],
)
serverOptionRequestDiskValue = fields.String(
    validate=(
        lambda x: memory_value_validation(x)
        if "disk_request" in config.SERVER_OPTIONS_UI.keys()
        else x == config.SERVER_OPTIONS_DEFAULTS["disk_request"]
    ),
    required=False,
    missing=config.SERVER_OPTIONS_DEFAULTS["disk_request"],
)
serverOptionRequestMemoryValue = fields.String(
    validate=(
        lambda x: memory_value_validation(x)
        if "mem_request" in config.SERVER_OPTIONS_UI.keys()
        else x == config.SERVER_OPTIONS_DEFAULTS["mem_request"]
    ),
    required=False,
    missing=config.SERVER_OPTIONS_DEFAULTS["mem_request"],
)
serverOptionRequestUrlValue = fields.Str(
    required=False, missing=config.SERVER_OPTIONS_DEFAULTS["defaultUrl"]
)
serverOptionRequestGpuValue = fields.Integer(
    strict=True,
    validate=(
        lambda x: x >= 0
        if "gpu_request" in config.SERVER_OPTIONS_UI.keys()
        else x == config.SERVER_OPTIONS_DEFAULTS["gpu_request"]
    ),
    missing=config.SERVER_OPTIONS_DEFAULTS["gpu_request"],
    required=False,
)
serverOptionRequestLfsAutoFetchValue = fields.Bool(
    validate=(
        lambda x: True
        if "lfs_auto_fetch" in config.SERVER_OPTIONS_UI.keys()
        else x == config.SERVER_OPTIONS_DEFAULTS["lfs_auto_fetch"]
    ),
    missing=config.SERVER_OPTIONS_DEFAULTS["lfs_auto_fetch"],
    required=False,
)


class LowercaseString(fields.String):
    """Basic class for a string field that always serializes
    and deserializes to lowercase string. Used for parameters that are
    case insensitive."""

    def _serialize(self, value, attr, obj, **kwargs):
        value = super()._serialize(value, attr, obj, **kwargs)
        if type(value) is str:
            return value.lower()
        else:
            raise ValidationError(
                f"The value {value} is not type string, but {type(value)}."
            )

    def _deserialize(self, value, attr, data, **kwargs):
        value = super()._deserialize(value, attr, data, **kwargs)
        if type(value) is str:
            return value.lower()
        else:
            raise ValidationError(
                f"The value {value} is not type string, but {type(value)}."
            )
