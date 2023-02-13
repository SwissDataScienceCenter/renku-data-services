from dataclasses import dataclass
from typing import Optional

from .common import GenericError


@dataclass
class ProgrammingError(GenericError):
    """
    *Error codes: from 2000 to 2999*

    The programming errors are bugs or unexpected cases. In the first case, they should lead
    to creating a new GitHub issue; in the latter, it may be necessary to handle the specific
    error to provide the user a precise explanation.
    """

    message: str = "You have found a bug"
    code: int = 2000
    status_code: int = 500
    detail: Optional[str] = "Please report this to the Renku maintainers."


@dataclass
class ConfigurationError(ProgrammingError):
    """Raised when there is a problem with the notebooks configuration"""

    message: str = "There seems to to be a misconfiguration in Renku."
    code: int = ProgrammingError.code + 1
    detail: Optional[str] = "Please contact your administrator."


@dataclass
class FilteringResourcesError(ProgrammingError):
    """Raised when a filtering operation returns larger than expected number of results.

    Usually all filtering operations (especially on k8s objects) are expected to return
    0 or 1 results but not more. If more results are found this error is raised.
    """

    message: str
    code: int = ProgrammingError.code + 2


@dataclass
class DuplicateEnvironmentVariableError(ProgrammingError):
    """Raised when amalthea patches are overriding an env var with different values."""

    message: str
    code: int = ProgrammingError.code + 3
