"""Base response validation used by services."""

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ValidationInfo
from pydantic import ValidationError as PydanticValidationError
from sanic import json
from sanic.response import JSONResponse

from renku_data_services import errors

RESPONSE_VALIDATION_CONTEXT = {"response": True}
NOT_NULLABLE_KEY = "x-not-nullable"


def reject_null_if_not_nullable(model: type[BaseModel], value: Any, info: ValidationInfo) -> Any:
    """Reject an explicit null for optional fields marked with `x-not-nullable: true` in the api spec.

    The code generator makes optional fields `X | None = None`, which accepts null even when the spec does not.
    The marker is passed through by the code generator with `--field-extra-keys` as `json_schema_extra`.
    Responses are not checked, a None value from the domain model there just means that the field is omitted.
    """
    if value is not None or info.field_name is None:
        return value
    if info.context is not None and info.context.get("response"):
        return value
    extra = model.model_fields[info.field_name].json_schema_extra
    if isinstance(extra, dict) and extra.get(NOT_NULLABLE_KEY):
        raise ValueError("null is not allowed")
    return value


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
