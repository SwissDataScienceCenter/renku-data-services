"""Background jobs utilities."""

import traceback
from collections.abc import Coroutine
from dataclasses import dataclass


@dataclass
class BackgroundJobError(Exception):
    """Error raised when an exception happenend in a background job."""

    message = "Background job failed:"
    errors: list[BaseException]

    def __format_errors__(self) -> str:
        """Format contained errors for output."""
        error_messages = []
        total_errors = len(self.errors)
        for i, error in enumerate(self.errors):
            error_messages.append(
                f"=== Error {i+1}/{total_errors} ===\n"
                + "".join(traceback.TracebackException.from_exception(error).format())
            )

        return "\n".join(error_messages)

    def __repr__(self) -> str:
        """String representation of the error."""
        return f"{self.__class__.__qualname__}: {self.message}\n{self.__format_errors__()}"

    def __str__(self) -> str:
        """String representation of the error."""
        return f"{self.__class__.__qualname__}: {self.message}\n{self.__format_errors__()}"


async def error_handler(tasks: list[Coroutine[None, None, None | list[BaseException]]]) -> None:
    """Run all contained tasks and raise an error at the end if any failed."""
    errors: list[BaseException] = []
    for task in tasks:
        try:
            result = await task
        except BaseException as err:
            errors.append(err)
        else:
            if result is not None:
                errors.extend(result)

    if len(errors) > 0:
        raise BackgroundJobError(errors=errors)
