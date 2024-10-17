import pytest

from renku_data_services import errors
from renku_data_services.background_jobs.utils import BackgroundJobError, ErrorHandler, ErrorHandlerMonad


@pytest.mark.asyncio
async def test_error_handler_without_errors():
    """Test the error handler behaves properly when there are no errors."""
    error_handler = ErrorHandler()

    async def add():
        return 1

    ec = await error_handler.map(add()).map(add()).map(add()).run()

    assert len(ec.errors) == 0

    ec.maybe_raise()


@pytest.mark.asyncio
async def test_error_handler_with_errors():
    """Test the error handler properly catches errors and raises them at the end."""
    error_handler = ErrorHandler()

    async def err1():
        raise errors.ValidationError()

    async def err2():
        raise ValueError("x is not set")

    async def err3():
        raise errors.UnauthorizedError()

    ec = await error_handler.map(err1()).map(err2()).map(err3()).run()

    assert len(ec.errors) == 3

    with pytest.raises(BackgroundJobError) as exc_info:
        ec.maybe_raise()

    exc_str = str(exc_info.value)
    assert errors.ValidationError.message in exc_str
    assert errors.UnauthorizedError.message in exc_str
    assert "x is not set" in exc_str


@pytest.mark.asyncio
async def test_error_handler_with_child_errors():
    """Check that returned errors from functions are handled correctly."""

    async def err1():
        raise errors.ValidationError()

    async def err2():
        return ErrorHandlerMonad([ValueError("x is not set"), ValueError("y is not set")])

    ec = await ErrorHandler().map(err1()).flatmap(err2()).run()

    assert len(ec.errors) == 3

    with pytest.raises(BackgroundJobError) as exc_info:
        ec.maybe_raise()

    exc_str = str(exc_info.value)
    assert errors.ValidationError.message in exc_str
    assert "x is not set" in exc_str
    assert "y is not set" in exc_str
