from dataclasses import dataclass
from typing import Optional

from .common import GenericError


@dataclass
class IntermittentError(GenericError):
    """
    *Error codes: from 3000 to 3999*

    This category includes errors that may temporarily affect the user, but they don't depend
    on a wrong input or can be classified as a bug. Repeating the same action after some
    time should be enough to solve the problem. If this is not the case then the
    system administrator or cloud provider can resolve these errors.
    An example could be a temporarily unavailable backend service (E.G. the GitLab instance)
    or a transient network problem.
    """

    message: str = "We seem to be experiencing some technical difficulties, please try again later."
    code: int = 3000
    status_code: int = 500
    detail: Optional[
        str
    ] = "If this problem persists please contact your administrator."


@dataclass
class DeleteServerError(IntermittentError):
    """Raised when a user server cannot be deleted. Usually occurs as a result of problems
    in k8s or amalthea."""

    message: str = (
        "The server cannot be deleted, most likely due to problems "
        "with the underlying infrastructure."
    )
    code: int = IntermittentError.code + 1


@dataclass
class CannotStartServerError(IntermittentError):
    """Raised when a user server cannot be started. Usually occurs as a result of problems
    in k8s or amalthea."""

    message: str = (
        "Cannot start the server, most likely due to problems "
        "with the underlying infrastructure."
    )
    code: int = IntermittentError.code + 2


@dataclass
class JSCacheError(IntermittentError):
    """Raised when the jupyter server cache responds with anything other than a 200 status
    code. This indicates trouble with the path requested (i.e. the jupyter cache is not aware
    of the path) or the jupyter server cache is not functioning properly. When this error
    is raised the regular (non-cached) k8s client takes over the fulfils the request. Please
    note that this is possible because the jupyter server cache will respond with 200 and
    an empty response if resource that do not exist are requested."""

    message: str = "The jupyter server cache produced and unexpected error."
    code: int = IntermittentError.code + 3


class RetryTimeoutError(IntermittentError):
    """Raised when something was expected to be retried and to eventually succeed but was retried
    too many times so that it timed out."""

    message: str = "Retrying the request timed out."
    code: int = IntermittentError.code + 4


@dataclass
class PatchServerError(IntermittentError):
    """Raised when a user server cannot be patched."""

    message: str = "The server cannot be patched."
    code: int = IntermittentError.code + 5


@dataclass
class PVDisabledError(IntermittentError):
    """Raised when cannot hibernating because PVs aren't enabled in the config."""

    message: str = "Persistent Volumes aren't enabled in the config."
    code: int = IntermittentError.code + 6


@dataclass
class AnonymousUserPatchError(IntermittentError):
    """Raised when trying to patch an anonymous user's session."""

    message: str = "Cannot patch sessions of anonymous users."
    code: int = IntermittentError.code + 7
    status_code: int = 422
