"""Base response validation used by services."""

from collections.abc import Callable
from dataclasses import asdict, is_dataclass
from typing import Any

from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError
from sanic import json
from sanic.response import JSONResponse

from renku_data_services import errors


def validate_and_dump(
    model: type[BaseModel],
    data: Any,
    exclude_none: bool = True,
    **kwargs: Any,
) -> Any:
    """Validate and dump with a pydantic model, ensuring proper validation errors.

    kwargs are passed on to the pydantic model `model_dump` method.
    """
    if is_dataclass(data) and not isinstance(data, type):
        data = asdict(data)
    try:
        body = model.model_validate(data).model_dump(exclude_none=exclude_none, mode="json", **kwargs)
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
