"""Base response validation used by services."""

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError
from sanic import json
from sanic.response import JSONResponse

from renku_data_services import errors


def validated_json(
    model: type[BaseModel],
    data: Any,
    status: int = 200,
    headers: dict[str, str] | None = None,
    content_type: str = "application/json",
    dumps: Callable[..., str] | None = None,
    exclude_none: bool = True,
    **kwargs: Any,
) -> JSONResponse:
    """Creates a JSON response with data validation.

    If the input data fails validation, an HTTP status code 500 will be raised.
    """
    try:
        body = model.model_validate(data).model_dump(exclude_none=exclude_none, mode="json")
    except PydanticValidationError as err:
        parts = [".".join(str(i) for i in field["loc"]) + ": " + field["msg"] for field in err.errors()]
        message = (
            f"The server could not construct a valid response. Errors found in the following fields: {', '.join(parts)}"
        )
        raise errors.ProgrammingError(message=message) from err
    return json(body, status=status, headers=headers, content_type=content_type, dumps=dumps, **kwargs)
