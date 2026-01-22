"""Methods for retrying requests."""

import asyncio
import functools
from collections.abc import Awaitable, Callable
from typing import Concatenate, ParamSpec, TypeVar

from renku_data_services.errors import errors

_RetType = TypeVar("_RetType")
_Params = ParamSpec("_Params")


def retry_with_exponential_backoff_async(
    should_retry: Callable[[_RetType], bool],
    num_retries: int = 10,
    initial_wait_ms: int = 20,
    multiplier: float = 2.0,
) -> Callable[
    [Callable[Concatenate[_Params], Awaitable[_RetType]]], Callable[Concatenate[_Params], Awaitable[_RetType]]
]:
    """Retries the wrapped function with an exponential backoff.

    The should_retry "callback" is passed the results from calling the wrapped function.
    If the response is true, the function is called again, otherwise the loop ends and
    the result of the wrapped function is returned.

    With the default values the wait times start with 20ms and then double every iteration.
    """

    def decorator_retry(
        func: Callable[Concatenate[_Params], Awaitable[_RetType]],
    ) -> Callable[Concatenate[_Params], Awaitable[_RetType]]:
        @functools.wraps(func)
        async def wrapper_retry(*args: _Params.args, **kwargs: _Params.kwargs) -> _RetType:
            for i in range(num_retries):
                res = await func(*args, **kwargs)
                if not should_retry(res):
                    return res

                await asyncio.sleep(initial_wait_ms * (multiplier**i) / 1000)
            raise errors.ProgrammingError(
                message=f"Retrying the function {func.__name__} timed out after {num_retries} retries."
            )

        return wrapper_retry

    return decorator_retry
