"""Base response validation used by services."""

from collections.abc import Callable
from datetime import date
from functools import cache
from typing import Any, get_args

from pydantic import AwareDatetime, BaseModel, NaiveDatetime, ValidationInfo
from pydantic import ValidationError as PydanticValidationError
from sanic import json
from sanic.response import JSONResponse

from renku_data_services import errors

RESPONSE_VALIDATION_CONTEXT = {"response": True}
NOT_NULLABLE_KEY = "x-not-nullable"


def _is_datetime_type(annotation: Any) -> bool:
    if annotation in (AwareDatetime, NaiveDatetime):
        return True
    if isinstance(annotation, type):
        return issubclass(annotation, date)
    return any(_is_datetime_type(arg) for arg in get_args(annotation))


def _is_number_type(annotation: Any) -> bool:
    if isinstance(annotation, type):
        return issubclass(annotation, int | float) and not issubclass(annotation, bool)
    return any(_is_number_type(arg) for arg in get_args(annotation))


def _is_bool_type(annotation: Any) -> bool:
    if isinstance(annotation, type):
        return issubclass(annotation, bool)
    return any(_is_bool_type(arg) for arg in get_args(annotation))


@cache
def _field_keys(model: type[BaseModel], is_type: Callable[[Any], bool]) -> dict[str, str]:
    """The input keys (name or alias) of the fields of a model with a matching type, mapped to the field name."""
    return {
        key: name
        for name, field in model.model_fields.items()
        if is_type(field.annotation)
        for key in (name, field.alias)
        if key is not None
    }


def validate_request_data(model: type[BaseModel], data: Any, info: ValidationInfo) -> Any:
    """Stricter validation of request data than what pydantic does by default.

    - Reject an explicit null for optional fields marked with `x-not-nullable: true` in the api spec.
      The code generator makes optional fields `X | None = None`, which accepts null even when the spec does not.
      The marker is passed through by the code generator with `--field-extra-keys` as `json_schema_extra`.
    - Reject numbers for date and datetime fields, the spec only allows strings but pydantic accepts unix timestamps.
    - Reject booleans for integer and number fields, pydantic converts them to 0 and 1.
    - Reject numbers for boolean fields, pydantic converts 0 and 1 to booleans. Strings are not rejected because
      query parameters are always strings.

    Responses are not checked, a None value from the domain model there just means that the field is omitted.
    NOTE: This has to be used in a model validator, pydantic does not allow `mode="before"` field validators
    on discriminator fields.
    """
    if not isinstance(data, dict):
        return data
    if info.context is not None and info.context.get("response"):
        return data
    null_fields = [
        name
        for name, field in model.model_fields.items()
        if isinstance(field.json_schema_extra, dict)
        and field.json_schema_extra.get(NOT_NULLABLE_KEY)
        and any(key in data and data[key] is None for key in (name, field.alias) if key is not None)
    ]
    if null_fields:
        raise ValueError(f"null is not allowed for: {', '.join(null_fields)}")
    number_fields = [
        name for key, name in _field_keys(model, _is_datetime_type).items() if isinstance(data.get(key), int | float)
    ]
    if number_fields:
        raise ValueError(f"a date-time string is required for: {', '.join(number_fields)}")
    bool_fields = [name for key, name in _field_keys(model, _is_number_type).items() if isinstance(data.get(key), bool)]
    if bool_fields:
        raise ValueError(f"a number is required for: {', '.join(bool_fields)}")
    number_for_bool_fields = [
        name
        for key, name in _field_keys(model, _is_bool_type).items()
        if isinstance(data.get(key), int | float) and not isinstance(data.get(key), bool)
    ]
    if number_for_bool_fields:
        raise ValueError(f"a boolean is required for: {', '.join(number_for_bool_fields)}")
    return data


def validate_and_dump(
    model: type[BaseModel],
    data: Any,
    exclude_none: bool = True,
    **kwargs: Any,
) -> Any:
    """Validate and dump with a pydantic model, ensuring proper validation errors.

    kwargs are passed on to the pydantic model `model_dump` method.
    """
    try:
        body = model.model_validate(data, context=RESPONSE_VALIDATION_CONTEXT).model_dump(
            exclude_none=exclude_none, mode="json", **kwargs
        )
    except PydanticValidationError as err:
        parts = [".".join(str(i) for i in field["loc"]) + ": " + field["msg"] for field in err.errors()]
        message = (
            f"The server could not construct a valid response. Errors found in the following fields: {', '.join(parts)}"
        )
        raise errors.ProgrammingError(message=message) from err
    return body


def validated_json(
    model: type[BaseModel],
    data: Any,
    status: int = 200,
    headers: dict[str, str] | None = None,
    content_type: str = "application/json",
    dumps: Callable[..., str] | None = None,
    exclude_none: bool = True,
    model_dump_kwargs: dict[str, Any] | None = None,
    **kwargs: Any,
) -> JSONResponse:
    """Creates a JSON response with data validation.

    If the input data fails validation, an HTTP status code 500 will be raised.
    """
    body = validate_and_dump(model, data, exclude_none, **(model_dump_kwargs or {}))
    return json(body, status=status, headers=headers, content_type=content_type, dumps=dumps, **kwargs)
