import pytest

from renku_data_services import errors
from renku_data_services.background_jobs.utils import BackgroundJobError, error_handler


@pytest.mark.asyncio
async def test_error_handler_without_errors():
    """Test the error handler behaves properly when there are no errors."""

    x = 0

    async def add():
        nonlocal x
        x += 1

    await error_handler([add(), add(), add()])
    assert x == 3


@pytest.mark.asyncio
async def test_error_handler_with_errors():
    """Test the error handler properly catches errors and raises them at the end."""

    async def err1():
        raise errors.ValidationError()

    async def err2():
        raise ValueError("x is not set")

    async def err3():
        raise errors.UnauthorizedError()

    with pytest.raises(BackgroundJobError) as exc_info:
        await error_handler([err1(), err2(), err3()])

    assert len(exc_info.value.errors) == 3
    exc_str = str(exc_info.value)
    assert errors.ValidationError.message in exc_str
    assert errors.UnauthorizedError.message in exc_str
    assert "x is not set" in exc_str


@pytest.mark.asyncio
async def test_error_handler_with_child_errors():
    """Check that returned errors from functions are handled correctly."""

    async def err1():
        raise errors.ValidationError()

    async def err2() -> list[BaseException]:
        return [ValueError("x is not set"), ValueError("y is not set")]

    with pytest.raises(BackgroundJobError) as exc_info:
        await error_handler([err1(), err2()])

    assert len(exc_info.value.errors) == 3

    exc_str = str(exc_info.value)
    assert errors.ValidationError.message in exc_str
    assert "x is not set" in exc_str
    assert "y is not set" in exc_str
