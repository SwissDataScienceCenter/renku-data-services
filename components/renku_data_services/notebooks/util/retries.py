"""Methods for retrying requests."""

import functools
from collections.abc import Callable
from time import sleep
from typing import Any

from ..errors.intermittent import RetryTimeoutError


def retry_with_exponential_backoff(
    should_retry: Callable[[Any], bool],
    num_retries: int = 10,
    initial_wait_ms: int = 20,
    multiplier: float = 2.0,
):
    """Retries the wrapped function with an exponential backoff.

    The should_retry "callback" is passed the results from calling the wrapped function.
    If the response is true, the function is called again, otherwise the loop ends and
    the result of the wrapped function is returned.

    With the default values the wait times start with 20ms and then double every iteration.
    """

    def decorator_retry(func):
        @functools.wraps(func)
        def wrapper_retry(*args, **kwargs):
            for i in range(num_retries):
                res = func(*args, **kwargs)
                if not should_retry(res):
                    return res
                sleep(initial_wait_ms * (multiplier**i) / 1000)
            raise RetryTimeoutError(f"Retrying the function {func.__name__} timed out after {num_retries} retries.")

        return wrapper_retry

    return decorator_retry
