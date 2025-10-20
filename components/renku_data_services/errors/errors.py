"""Exceptions for the server."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Optional

from ulid import ULID


@dataclass
class BaseError(Exception):
    """Base class for all exceptions."""

    code: int = 1500
    status_code: int = 500
    message: str = "An unexpected error occurred"
    detail: Optional[str] = None
    quiet: bool = False

    def __repr__(self) -> str:
        """String representation of the error."""
        return f"{self.__class__.__qualname__}: {self.message}"

    def __str__(self) -> str:
        """String representation of the error."""
        return f"{self.__class__.__qualname__}: {self.message}"


# ! IMPORTANT: keep this list ordered by HTTP status code.


@dataclass
class GeneralBadRequest(BaseError):
    """Raised for a 400 status code - when the server cannot or will not process the request."""

    code: int = 1400
    message: str = "The request is invalid, malformed or non-sensical and cannot be fulfilled."
    status_code: int = 400


@dataclass
class UnauthorizedError(BaseError):
    """Raised when the user does not have the required credentials."""

    code: int = 1401
    message: str = "Credentials need to be supplied for this operation."
    status_code: int = 401
    quiet: bool = True


@dataclass
class InvalidTokenError(UnauthorizedError):
    """The supplied jwt is invalid."""

    message: str = "The supplied credentials (jwt) are not valid."


@dataclass
class ForbiddenError(BaseError):
    """Raised when the provided credentials do not grant permission for the current operation."""

    code: int = 1403
    message: str = "The supplied credentials do not grant permission for this operation."
    status_code: int = 403
    quiet: bool = True


@dataclass
class CopyDataConnectorsError(ForbiddenError):
    """Raised when a project can be copied but its data connectors cannot be copied due to lack of permission."""

    message: str = "The project was copied but there is no permission to copy data connectors."


@dataclass
class MissingResourceError(BaseError):
    """Raised when a resource is not found."""

    code: int = 1404
    status_code: int = 404
    message: str = "The requested resource does not exist or cannot be found"
    quiet: bool = True


@dataclass
class ConflictError(BaseError):
    """Raised when a conflicting update occurs."""

    code: int = 1409
    message: str = "Conflicting update detected."
    status_code: int = 409


@dataclass
class UpdatingWithStaleContentError(BaseError):
    """Raised when the request content for an update is old or outdated.

    Mostly used when an old resource slug is used to patch a resource. In these cases it is hard for the
    server to understand what is the intention of the client. The best option in this case is for the client
    to refresh its state and send a new request with the latest slug for the resource in question.
    """

    code: int = 1409
    message: str = "The content of the update request is out of date."
    detail: str = "Please refresh the state on the client by sending a GET request and retry the update."
    status_code: int = 409


@dataclass
class ValidationError(BaseError):
    """Raised when the inputs or outputs are invalid."""

    code: int = 1422
    message: str = "The provided input is invalid"
    status_code: int = 422


@dataclass
class PreconditionRequiredError(BaseError):
    """Raised when a precondition is not met."""

    code: int = 1428
    message: str = "Conflicting update detected."
    status_code: int = 428


@dataclass
class ConfigurationError(BaseError):
    """Raised when the server is not properly configured."""

    message: str = "The server is not properly configured and cannot run"


@dataclass
class ProgrammingError(BaseError):
    """Raised an irrecoverable programming error or bug occurs."""

    code: int = 1500
    message: str = "An unexpected error occurred."
    status_code: int = 500


@dataclass
class EventError(BaseError):
    """Raised an irrecoverable error when generating events for the message queue."""

    code: int = 1501
    message: str = "An unexpected error occurred when handling or generating events for the message queue."
    status_code: int = 500


@dataclass
class SecretDecryptionError(BaseError):
    """Raised when an error occurs decrypting secrets."""

    code: int = 1510
    message: str = "An error occurred decrypting secrets."
    status_code: int = 500


@dataclass
class SecretCreationError(BaseError):
    """Raised when an error occurs creating secrets."""

    code: int = 1511
    message: str = "An error occurred creating secrets."
    status_code: int = 500


@dataclass
class CannotStartBuildError(ProgrammingError):
    """Raised when an image build couldn't be started."""

    code: int = 1512
    message: str = "An error occurred creating an image build."


@dataclass
class RequestCancelledError(ProgrammingError):
    """Raised when the server is stopped or the client making the request stops it before it finishes."""

    code: int = 1513
    message: str = (
        "The server was stopped or the client making the request stopped it before it finished. "
        "Please just retry the reuqest."
    )


def missing_or_unauthorized(resource_type: str | StrEnum, id: str | int | ULID) -> MissingResourceError:
    """Generate a missing resource error with an ambiguous message."""
    return MissingResourceError(
        message=f"The {resource_type} with ID {id} does not exist or "
        "you do not have sufficient permissions to access it",
    )
