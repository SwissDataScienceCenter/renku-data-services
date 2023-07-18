import inspect
from typing import Any, Awaitable, Callable, Dict

import pytest
from renku_data_services.crc_schemas import apispec
from renku_data_services.models import errors
from sanic import Request, Sanic, SanicException
from sanic.models.handler_types import RouteHandler
from sanic_ext.exceptions import ValidationError as SanicValidationError
from sanic_testing.testing import SanicTestClient
from sqlalchemy.exc import SQLAlchemyError

from renku_data_services.crc_api.error_handler import CustomErrorHandler


def _trigger_error(err: Exception | Callable | Awaitable) -> RouteHandler:
    async def _handler(_: Request):
        if callable(err):
            err()
        elif inspect.isawaitable(err):
            await err
        elif isinstance(err, Exception):
            raise err

    return _handler


def _generate_pydantic_error():
    apispec.QuotaPatch.validate({"cpu": -1.0})


@pytest.mark.parametrize(
    "err,expected_response,expected_status_code",
    [
        (
            errors.ValidationError(message="Test validation error"),
            apispec.ErrorResponse(error=apispec.Error(code=1422, message="Test validation error", detail=None)).dict(
                exclude_none=True
            ),
            422,
        ),
        (
            Exception(),
            apispec.ErrorResponse(error=apispec.Error.from_orm(errors.BaseError())).dict(exclude_none=True),
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
                )
            ).dict(exclude_none=True),
            422,
        ),
        (
            _generate_pydantic_error,
            apispec.ErrorResponse(
                error=apispec.Error(
                    code=1422,
                    message="There are errors in the following fields, cpu: ensure this value is greater than 0.0",
                    detail=None,
                )
            ).dict(exclude_none=True),
            422,
        ),
        (
            SanicValidationError(
                message="test_message",
                extra={"exception": Exception()},
            ),
            apispec.ErrorResponse(error=apispec.Error.from_orm(errors.BaseError())).dict(exclude_none=True),
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
                )
            ).dict(exclude_none=True),
            500,
        ),
        (
            SQLAlchemyError("some", "error"),
            apispec.ErrorResponse(
                error=apispec.Error(
                    code=1500,
                    message="Database error occurred: some, error",
                    detail=None,
                )
            ).dict(exclude_none=True),
            500,
        ),
    ],
)
def test_error_handler(err: Exception | Callable, expected_response: Dict[str, Any], expected_status_code: int):
    app = Sanic("test-error-handler")
    app.error_handler = CustomErrorHandler()
    app.get("/")(_trigger_error(err))  # type: ignore[unused-coroutine]
    test_client = SanicTestClient(app)
    _, res = test_client.get("/")
    assert res.status_code == expected_status_code
    assert res.json == expected_response
