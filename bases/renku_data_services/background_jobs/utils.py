"""Background jobs utilities."""

import traceback
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from types import TracebackType


@dataclass
class BackgroundJobError(Exception):
    """Error raised when an exception happenend in a background job."""

    message = "Background job failed:"
    errors: list[BaseException]

    def __format_errors__(self) -> str:
        """Format contained errors for output."""
        result = []
        for error in self.errors:
            result.append("".join(traceback.TracebackException.from_exception(error).format()))
        return "\n".join(result)

    def __repr__(self) -> str:
        """String representation of the error."""
        return f"{self.__class__.__qualname__}: {self.message}\n{self.__format_errors__()}"

    def __str__(self) -> str:
        """String representation of the error."""
        return f"{self.__class__.__qualname__}: {self.message}\n{self.__format_errors__()}"


class ErrorHandler(AbstractAsyncContextManager):
    """A context manager that collects and suppresses errors.

    `maybe_raise` can be used to raise an exception if the contextmanager collected any errors.
    """

    def __init__(self) -> None:
        """Initialize the error handler."""
        self.errors: list[BaseException] = list()

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc_value: BaseException | None, traceback: TracebackType | None, /
    ) -> bool:
        """Exit function called when the context manager exits."""
        if exc_value:
            self.errors.append(exc_value)

        return True

    def maybe_raise(self) -> None:
        """If this handler captured any errors, we raise them here. Otherwise to nothing."""
        if len(self.errors) > 0:
            raise BackgroundJobError(errors=self.errors)
