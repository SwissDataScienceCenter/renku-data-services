"""The error handler for the application."""

from sqlite3 import Error as SqliteError
from typing import AbstractSet, Any, Dict, Mapping, Optional, Protocol, TypeVar, Union

from asyncpg import exceptions as postgres_exceptions
from pydantic import ValidationError as PydanticValidationError
from pydantic.error_wrappers import ValidationError as PydanticWrappersValidationError
from sanic import HTTPResponse, Request, SanicException, json
from sanic.errorpages import BaseRenderer, TextRenderer
from sanic.handlers import ErrorHandler
from sanic.log import logger
from sanic_ext.exceptions import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from renku_data_services import errors


class BaseError(Protocol):
    """Protocol for the error type of an apispec module."""

    code: int
    message: str
    detail: Optional[str]


class BaseErrorResponse(Protocol):
    """Porotocol for the error response class of an apispec module."""

    error: BaseError

    def dict(
        self,
        *,
        include: Optional[Union[AbstractSet[Union[int, str]], Mapping[Union[int, str], Any]]] = None,
        exclude: Optional[Union[AbstractSet[Union[int, str]], Mapping[Union[int, str], Any]]] = None,
        by_alias: bool = False,
        skip_defaults: Optional[bool] = None,
        exclude_unset: bool = False,
        exclude_defaults: bool = False,
        exclude_none: bool = False,
    ) -> Dict[str, Any]:
        """Turn the response to dict."""
        ...


BError = TypeVar("BError", bound=BaseError)
BErrorResponse = TypeVar("BErrorResponse", bound=BaseErrorResponse)


class ApiSpec(Protocol[BErrorResponse, BError]):
    """Protocol for an apispec with error data."""

    ErrorResponse: BErrorResponse
    Error: BError


class CustomErrorHandler(ErrorHandler):
    """Central error handling."""

    def __init__(self, api_spec: ApiSpec, base: type[BaseRenderer] = TextRenderer):
        self.api_spec = api_spec
        super().__init__(base)

    def _log_unhandled_exception(self, exception: Exception):
        if self.debug:
            logger.exception("An unknown or unhandled exception occurred", exc_info=exception)
        logger.error("An unknown or unhandled exception of type %s occurred", type(exception).__name__)

    def default(self, request: Request, exception: Exception) -> HTTPResponse:
        """Overrides the default error handler."""
        formatted_exception = errors.BaseError()
        logger.exception("An unknown or unhandled exception occurred", exc_info=exception)
        match exception:
            case errors.BaseError():
                formatted_exception = exception
            case ValidationError():
                extra_exception = None if exception.extra is None else exception.extra["exception"]
                match extra_exception:
                    case TypeError():
                        formatted_exception = errors.ValidationError(
                            message="The validation failed because the provided input has the wrong type"
                        )
                    case PydanticValidationError():
                        parts = [
                            ".".join(str(i) for i in field["loc"]) + ": " + field["msg"]
                            for field in extra_exception.errors()
                        ]
                        message = f"There are errors in the following fields, {', '.join(parts)}"
                        formatted_exception = errors.ValidationError(message=message)
                    case _:
                        self._log_unhandled_exception(exception)
            case SanicException():
                message = exception.message
                if message == "" or message is None:
                    message = ", ".join([str(i) for i in exception.args])
                formatted_exception = errors.BaseError(
                    message=message, status_code=exception.status_code, code=1000 + exception.status_code
                )
            case SqliteError():
                formatted_exception = errors.BaseError(
                    message=f"Database error occurred: {exception.sqlite_errorname}",
                    detail=f"Error code: {exception.sqlite_errorcode}",
                )
            case postgres_exceptions.PostgresError():
                formatted_exception = errors.BaseError(
                    message=f"Database error occurred: {exception.msg}", detail=f"Error code: {exception.pgcode}"
                )
            case SQLAlchemyError():
                message = ", ".join([str(i) for i in exception.args])
                formatted_exception = errors.BaseError(message=f"Database error occurred: {message}")
            case PydanticWrappersValidationError() | PydanticValidationError():  # type: ignore[misc]
                parts = [".".join(str(i) for i in field["loc"]) + ": " + field["msg"] for field in exception.errors()]
                message = f"There are errors in the following fields, {', '.join(parts)}"
                formatted_exception = errors.ValidationError(message=message)
            case OverflowError():
                formatted_exception = errors.ValidationError(
                    message="The provided input is too large to be stored in the database"
                )
            case _:
                self._log_unhandled_exception(exception)
        return json(
            self.api_spec.ErrorResponse(
                error=self.api_spec.Error(
                    code=formatted_exception.code,
                    message=formatted_exception.message,
                    detail=formatted_exception.detail,
                )
            ).model_dump(exclude_none=True),
            status=formatted_exception.status_code,
        )
