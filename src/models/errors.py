"""Exceptions for the server."""
from dataclasses import dataclass
from typing import Optional


@dataclass
class BaseError(Exception):
    """Base class for all exceptions."""

    code: int = 1500
    status_code: int = 500
    message: str = "An unexpected error occured"
    detail: Optional[str] = None


@dataclass
class MissingResourceError(BaseError):
    """Raised when a resource is not found."""

    code: int = 1404
    status_code: int = 404
    message: str = "The reqested resource does not exist or cannot be found"


@dataclass
class ConfigurationError(BaseError):
    """Raised when the serverver is not properly configured."""

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
