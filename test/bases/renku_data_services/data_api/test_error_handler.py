import inspect
import re
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from sanic import Request, Sanic, SanicException
from sanic.models.handler_types import RouteHandler
from sanic_ext.exceptions import ValidationError as SanicValidationError
from sanic_testing.testing import SanicTestClient
from sqlalchemy.exc import SQLAlchemyError

from renku_data_services import errors
from renku_data_services.base_api.error_handler import CustomErrorHandler
from renku_data_services.crc import apispec


def _trigger_error(err: Exception | Callable | Awaitable) -> RouteHandler:
    async def _handler(_: Request):
        if callable(err):
            err()
        elif inspect.isawaitable(err):
            await err
        elif isinstance(err, Exception):
            raise err

    return _handler


def _generate_pydantic_error() -> None:
    apispec.QuotaPatch.model_validate({"cpu": -1.0})


@pytest.mark.parametrize(
    "err,expected_response,expected_status_code",
    [
        (
            errors.ValidationError(message="Test validation error"),
            apispec.ErrorResponse(
                error=apispec.Error(code=1422, message="Test validation error", detail=None, trace_id=None)
            ).model_dump(exclude_none=True),
            422,
        ),
        (
            Exception(),
            apispec.ErrorResponse(error=apispec.Error.model_validate(errors.BaseError())).model_dump(exclude_none=True),
            500,
        ),
        (
            SanicValidationError(
                message="test_message",
                extra={"exception": TypeError()},
            ),
            apispec.ErrorResponse(
                error=apispec.Error(
                    code=1422,
                    message="The validation failed because the provided input has the wrong type",
                    detail=None,
                    trace_id=None,
                )
            ).model_dump(exclude_none=True),
            422,
        ),
        (
            _generate_pydantic_error,
            apispec.ErrorResponse(
                error=apispec.Error(
                    code=1422,
                    message="There are errors in the following fields, cpu: Input should be greater than 0",
                    detail=None,
                    trace_id=None,
                )
            ).model_dump(exclude_none=True),
            422,
        ),
        (
            SanicValidationError(
                message="test_message",
                extra={"exception": Exception()},
            ),
            apispec.ErrorResponse(error=apispec.Error.model_validate(errors.BaseError())).model_dump(exclude_none=True),
            500,
        ),
        (
            SanicException(
                message="test_message",
            ),
            apispec.ErrorResponse(
                error=apispec.Error(
                    code=1500,
                    message="test_message",
                    detail=None,
                    trace_id=None,
                )
            ).model_dump(exclude_none=True),
            500,
        ),
        (
            SQLAlchemyError("some", "error"),
            apispec.ErrorResponse(
                error=apispec.Error(
                    code=1500,
                    message="Database error occurred: some, error",
                    detail=None,
                    trace_id=None,
                )
            ).model_dump(exclude_none=True),
            500,
        ),
    ],
)
def test_error_handler(err: Exception | Callable, expected_response: dict[str, Any], expected_status_code: int) -> None:
    app = Sanic("test-error-handler")
    app.error_handler = CustomErrorHandler(apispec)
    app.get("/")(_trigger_error(err))  # type: ignore[unused-coroutine]
    test_client = SanicTestClient(app)
    _, res = test_client.get("/")
    assert res.status_code == expected_status_code
    assert res.json == expected_response


def test_sentry_trace_id_is_included_in_errors(dummy_sentry):
    app = Sanic("test-error-handler")
    app.error_handler = CustomErrorHandler(apispec)
    app.get("/")(_trigger_error(Exception("test")))  # type: ignore[unused-coroutine]
    test_client = SanicTestClient(app)

    _, response = test_client.get("/")

    assert response.status_code == 500
    # trace_id is included in the error response and is a UUID
    assert "trace_id" in response.json["error"]
    assert re.match(r"^[0-9a-fA-F]{32}$", response.json["error"]["trace_id"])

    # Set a specific trace_id
    trace_id = "4bf92f3577b34da6a3ce929d0e0e4736"
    _, response = test_client.get("/", headers={"sentry-trace": f"{trace_id}-0123456789abcdef-0"})

    assert response.status_code == 500
    assert response.json["error"]["trace_id"] == trace_id
