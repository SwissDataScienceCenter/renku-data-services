"""The error handler for the application."""
from sqlite3 import Error as SqliteError

from asyncpg import exceptions as postgres_exceptions
from pydantic import ValidationError as PydanticValidationError
from pydantic.error_wrappers import ValidationError as PydanticWrappersValidationError
from sanic import HTTPResponse, Request, SanicException, json
from sanic.handlers import ErrorHandler
from sanic.log import logger
from sanic_ext.exceptions import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from models import errors
from schemas import apispec


class CustomErrorHandler(ErrorHandler):
    """Central error handling."""

    def _log_unhandled_exception(self, exception: Exception):
        if self.debug:
            logger.exception("An unknown or unhandled exception occurred", exc_info=exception)
        logger.error("An unknown or unhandled exception of type %s occurred", type(exception).__name__)

    def default(self, request: Request, exception: Exception) -> HTTPResponse:
        """Overrides the default error handler."""
        formatted_exception = errors.BaseError()
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
            case PydanticWrappersValidationError():
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
            apispec.ErrorResponse(
                error=apispec.Error(
                    code=formatted_exception.code,
                    message=formatted_exception.message,
                    detail=formatted_exception.detail,
                )
            ).dict(exclude_none=True),
            status=formatted_exception.status_code,
        )
