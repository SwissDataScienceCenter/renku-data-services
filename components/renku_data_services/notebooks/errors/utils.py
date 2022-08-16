import logging

from werkzeug.exceptions import HTTPException

from ..api.schemas.errors import (
    ErrorResponseFromGenericError,
    ErrorResponseFromWerkzeug,
)
from .common import GenericError


def handle_exception(e):
    """Central exception handling for the whole app."""
    if isinstance(e, HTTPException):
        # start with the correct headers and status code from the error
        response = e.get_response()
        # replace the body with JSON
        response.data = ErrorResponseFromWerkzeug().dumps(e)
        response.content_type = "application/json"
        return response
    elif isinstance(e, GenericError):
        return ErrorResponseFromGenericError().dump(e), e.status_code
    else:
        logging.exception("Unexpected error occured.")
        generic_error = GenericError()
        return ErrorResponseFromGenericError().dump(generic_error), 500
