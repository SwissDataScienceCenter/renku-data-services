from marshmallow import fields
from marshmallow.exceptions import ValidationError
import re


class CpuField(fields.Field):
    """
    Field that handles cpu requests/limits in the same format as k8s.
    """

    _validation_regex = r"^(?<!-)([0-9]*\.?[0-9]*)(m?)$"

    def _serialize(self, value, attr, obj, **kwargs):
        if type(value) is not float and type(value) is not int:
            raise ValidationError(
                f"Invalid value {value} during serialization, "
                f"must be int or float, got {type(value)}."
            )
        if value < 0:
            raise ValidationError(
                "Invalid value during serialization, must be greater than zero."
            )
        return value

    def _deserialize(self, value, attr, data, **kwargs):
        """Always deserialize to fractional cores"""
        re_match = re.match(self._validation_regex, str(value))
        if re_match is None:
            raise ValidationError(
                f"Unexpected format for cpu, must match regex {self._validation_regex}."
            )
        num, unit = re_match.groups()
        try:
            num = float(num)
        except ValueError as error:
            raise ValidationError(
                f"Cannot convert {num} to float as fractional cores."
            ) from error
        if unit == "m":
            num = num / 1000
        return num


class MemoryField(fields.Field):
    """
    Field that handles memory/disk requests/limits in the same format as k8s.
    """

    _validation_regex = r"^(?<!-)([0-9]*\.?[0-9]*)((?<=[0-9.])[EPTGMKeptgmkbBi]*)$"
    _to_bytes_conversion = {
        "b": 1,
        "kb": 1000,
        "mb": 1000**2,
        "gb": 1000**3,
        "tb": 1000**4,
        "pb": 1000**5,
        "eb": 1000**6,
        "k": 1000,
        "m": 1000**2,
        "g": 1000**3,
        "t": 1000**4,
        "p": 1000**5,
        "e": 1000**6,
        "ki": 1024,
        "mi": 1024**2,
        "gi": 1024**3,
        "ti": 1024**4,
        "pi": 1024**5,
        "ei": 1024**6,
    }

    def _serialize(self, value, attr, obj, **kwargs):
        """Assumes value to be serialized is always bytes, serialized to gigabytes."""
        if type(value) is not float and type(value) is not int:
            raise ValidationError(
                f"Invalid value {value} during serialization, "
                f"must be int or float, got {type(value)}."
            )
        if value < 0:
            raise ValidationError(
                "Invalid value during serialization, must be greater than zero."
            )
        if (value / 1000000000) % 1 > 0:
            # If value has decimals round to 2 decimals in response
            return "{:.2f}G".format(value / 1000000000)
        else:
            return "{:.0f}G".format(value / 1000000000)

    def _deserialize(self, value, attr, data, **kwargs):
        """Always deserialize to bytes"""
        re_match = re.match(self._validation_regex, str(value))
        if re_match is None:
            raise ValidationError(
                f"Unexpected format for memory, must match regex {self._validation_regex}."
            )
        num, unit = re_match.groups()
        unit_lowercase = unit.lower()
        if len(unit) != 0 and unit_lowercase not in self._to_bytes_conversion:
            raise ValidationError(
                f"Cannot recognize unit {unit} for memory or disk space."
            )
        bytes_conversion_factor = self._to_bytes_conversion.get(unit_lowercase, 1)
        try:
            num = float(num)
        except ValueError as error:
            raise ValidationError(f"Cannot convert {num} to float.") from error
        return num * bytes_conversion_factor


class GpuField(fields.Field):
    """
    Field that handles GPU requests/limits in the same format as k8s.
    """

    _validation_regex = r"^(?<!-)([0-9]*\.?[0-9]*)$"

    def _serialize(self, value, attr, obj, **kwargs):
        """
        Assumes value to be serialized is always whole GPUs.
        It is not possible to request a fraction of GPU in k8s.
        """
        if type(value) is not int and type(value) is not float:
            raise ValidationError(
                f"Invalid value during GPU amount serialization, must be int or float, got {value}."
            )
        if type(value) is float:
            if value % 1 != 0:
                raise ValidationError(
                    "Invalid value during GPU amount serialization, "
                    f"must not be decimal number, got {value}."
                )
            value = int(value)
        if value < 0:
            raise ValidationError(
                "Invalid value during GPU amount serialization, "
                f"must be greater than or equal to zero, got {value}."
            )
        return value

    def _deserialize(self, value, attr, data, **kwargs):
        """Always deserialize to whole GPUs as integer."""
        re_match = re.match(self._validation_regex, str(value))
        if re_match is None:
            raise ValidationError(
                f"Unexpected format for GPUs, must match regex {self._validation_regex}."
            )
        num = re_match.groups()[0]
        try:
            num = float(num)
        except ValueError as error:
            raise ValidationError(
                f"Cannot convert {num} of GPUs to integer."
            ) from error
        if num % 1 != 0:
            raise ValidationError(
                "Invalid value during GPU amount deserialization, "
                f"must not be decimal number, got {value}."
            )
        num = int(num)
        return num


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
