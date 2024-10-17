import pytest

from renku_data_services import errors
from renku_data_services.background_jobs.utils import BackgroundJobError, ErrorHandler


@pytest.mark.asyncio
async def test_error_handler_without_errors():
    """Test the error handler behaves properly when there are no errors."""
    error_handler = ErrorHandler()

    async with error_handler:
        x = 1 + 1

    async with error_handler:
        y = 2 + 2

    async with error_handler:
        z = 3 + 3

    assert x == 2
    assert y == 4
    assert z == 6

    assert len(error_handler.errors) == 0

    error_handler.maybe_raise()


@pytest.mark.asyncio
async def test_error_handler_with_errors():
    """Test the error handler properly catches errors and raises them at the end."""
    error_handler = ErrorHandler()

    async with error_handler:
        raise errors.ValidationError()

    async with error_handler:
        raise ValueError("x is not set")

    async with error_handler:
        raise errors.UnauthorizedError()

    assert len(error_handler.errors) == 3

    with pytest.raises(BackgroundJobError) as exc_info:
        error_handler.maybe_raise()

    exc_str = str(exc_info.value)
    assert errors.ValidationError.message in exc_str
    assert errors.UnauthorizedError.message in exc_str
    assert "x is not set" in exc_str
