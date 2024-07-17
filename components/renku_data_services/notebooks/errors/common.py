"""Generic errors."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class GenericError(Exception):
    """A generic error class that is the parent class of all API errors raised by the notebook service code."""

    message: str = "Something went wrong."
    code: int = 2000
    detail: Optional[str] = None
    status_code: int = 500
