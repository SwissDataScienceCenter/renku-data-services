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
    exclude_none: bool = True,
    status: int = 200,
    headers: dict[str, str] | None = None,
    content_type: str = "application/json",
    dumps: Callable[..., str] | None = None,
    **kwargs: Any,
) -> JSONResponse:
    """Creates a JSON response with data validation."""
    try:
        body = model.model_validate(data).model_dump(exclude_none=exclude_none, mode="json")
    except PydanticValidationError as err:
        raise errors.ProgrammingError from err
    return json(body, status=status, headers=headers, content_type=content_type, dumps=dumps, **kwargs)
