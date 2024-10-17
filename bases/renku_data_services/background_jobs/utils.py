"""Background jobs utilities."""

import traceback
from collections.abc import Coroutine
from dataclasses import dataclass
from typing import Self


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


class ErrorHandlerMonad:
    """A monad for tracking exceptions of computational steps."""

    def __init__(self, errors: list[BaseException]) -> None:
        self.errors = errors

    async def map(self, fn: Coroutine[None, None, None] | list[Coroutine[None, None, None]]) -> Self:
        """Await a single or list of coroutines and track an error if it occurs.

        For a list of coroutines, if any of them fail, subsequent ones aren't executed.
        """
        try:
            if isinstance(fn, list):
                for f in fn:
                    await f
            else:
                await fn
        except BaseException as e:
            self.errors.append(e)
        return self

    async def flatmap(
        self, fn: "Coroutine[None,None,ErrorHandlerMonad]|list[Coroutine[None,None,ErrorHandlerMonad]]"
    ) -> Self:
        """Await a single or list of coroutines that return ErrorHandlerMonads and track an errors if they occur.

        For a list of coroutines, if any of them fail, subsequent ones aren't executed.
        ErrorsHandlerMonads of contained coroutines are rolled into this one if all the coroutines succeeded.
        """
        handler = ErrorHandlerMonad([])
        try:
            if isinstance(fn, list):
                for f in fn:
                    result = await f
                    handler.errors.extend(result.errors)

            else:
                handler = await fn
        except BaseException as e:
            self.errors.append(e)
        else:
            self.errors.extend(handler.errors)

        return self

    def maybe_raise(self) -> None:
        """If this handler captured any errors, we raise them here. Otherwise do nothing."""
        if len(self.errors) > 0:
            raise BackgroundJobError(errors=self.errors)


class _MapTask:
    """A simple task that doesn't have child errors."""

    def __init__(self, task: Coroutine[None, None, None] | list[Coroutine[None, None, None]]) -> None:
        self.task = task


class _FlatMapTask:
    """A task that can return child errors."""

    def __init__(
        self, task: Coroutine[None, None, ErrorHandlerMonad] | list[Coroutine[None, None, ErrorHandlerMonad]]
    ) -> None:
        self.task = task


class ErrorHandler:
    """Error handler builder.

    This is required because tasks are async and we can't use the ErrorHandlerMonad directly.
    """

    tasks: list[_MapTask | _FlatMapTask]

    def __init__(self) -> None:
        """Initialize the builder."""
        self.tasks = list()

    def map(self, fns: Coroutine[None, None, None] | list[Coroutine[None, None, None]]) -> Self:
        """Add a new task."""
        self.tasks.append(_MapTask(fns))
        return self

    def flatmap(
        self, fns: Coroutine[None, None, ErrorHandlerMonad] | list[Coroutine[None, None, ErrorHandlerMonad]]
    ) -> Self:
        """Add a new task that returns an ErrorHandlerMonad containing potential child errors."""
        self.tasks.append(_FlatMapTask(fns))
        return self

    async def run(self) -> ErrorHandlerMonad:
        """Run all tasks, returning collected errors."""
        eh = ErrorHandlerMonad([])
        for task in self.tasks:
            if isinstance(task, _MapTask):
                eh = await eh.map(task.task)
            else:
                eh = await eh.flatmap(task.task)

        return eh
