"""Exceptions for the server."""
from dataclasses import dataclass
from typing import Optional


@dataclass
class BaseError(Exception):
    """Base class for all exceptions."""

    code: int = 1500
    status_code: int = 500
    message: str = "An unexpected error occurred"
    detail: Optional[str] = None

    def __repr__(self):
        """String representation of the error."""
        return f"{self.__class__.__qualname__}: {self.message}"

    def __str__(self):
        """String representation of the error."""
        return f"{self.__class__.__qualname__}: {self.message}"


@dataclass
class MissingResourceError(BaseError):
    """Raised when a resource is not found."""

    code: int = 1404
    status_code: int = 404
    message: str = "The requested resource does not exist or cannot be found"


@dataclass
class ConfigurationError(BaseError):
    """Raised when the server is not properly configured."""

    message: str = "The server is not properly configured and cannot run"


@dataclass
class ValidationError(BaseError):
    """Raised when the inputs or outputs are invalid."""

    code: int = 1422
    message: str = "The provided input is invalid"
    status_code: int = 422


@dataclass
class Unauthorized(BaseError):
    """Raised when the user does not have the required credentials."""

    code: int = 1401
    message: str = "The supplied credentials are missing or invalid."
    status_code: int = 401


@dataclass
class NoDefaultPoolAccessError(BaseError):
    """Raised when the user does not have the right to access the default resource pool."""

    code: int = 1400
    message: str = "The user cannot access the default resource pool."
    status_code: int = 400


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
class ProgrammingError(BaseError):
    """Raised an irrecoverable programming error or bug occurs."""

    code: int = 1500
    message: str = "An unexpected error occurred."
    status_code: int = 500
