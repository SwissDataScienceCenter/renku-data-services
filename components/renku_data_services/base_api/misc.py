"""Common blueprints."""

from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass
from functools import wraps
from typing import Any, Concatenate, NoReturn, ParamSpec, TypeVar, cast

from pydantic import BaseModel
from sanic import Request, json
from sanic.response import JSONResponse
from sanic_ext import validate

from renku_data_services import errors
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint


@dataclass(kw_only=True)
class MiscBP(CustomBlueprint):
    """Server contains all handlers for CRC and the configuration."""

    apispec: dict[str, Any]
    version: str

    def get_apispec(self) -> BlueprintFactoryResponse:
        """Servers the OpenAPI specification."""

        async def _get_apispec(_: Request) -> JSONResponse:
            return json(self.apispec)

        return "/spec.json", ["GET"], _get_apispec

    def get_error(self) -> BlueprintFactoryResponse:
        """Returns a sample error response."""

        async def _get_error(_: Request) -> NoReturn:
            raise errors.ValidationError(message="Sample validation error")

        return "/error", ["GET"], _get_error

    def get_version(self) -> BlueprintFactoryResponse:
        """Returns the version."""

        async def _get_version(_: Request) -> JSONResponse:
            return json({"version": self.version})

        return "/version", ["GET"], _get_version


_T = TypeVar("_T")
_P = ParamSpec("_P")


def validate_db_ids(f: Callable[_P, Awaitable[_T]]) -> Callable[_P, Coroutine[Any, Any, _T]]:
    """Decorator for a Sanic handler that errors out if passed in IDs are outside of the valid range for postgres."""

    @wraps(f)
    async def decorated_function(*args: _P.args, **kwargs: _P.kwargs) -> _T:
        resource_pool_id = cast(int | None, kwargs.get("resource_pool_id"))
        class_id = cast(int | None, kwargs.get("class_id"))
        min_val = 1  # postgres primary keys start at 1
        max_val = 2_147_483_647  # the max value for a default postgres primary key sequence
        if resource_pool_id and not min_val <= resource_pool_id <= max_val:
            raise errors.ValidationError(
                message=f"The provided resource pool ID is outside of the allowed range [{min_val}, {max_val}]"
            )
        if class_id and not min_val <= class_id <= max_val:
            raise errors.ValidationError(
                message=f"The provided resource class ID is outside of the allowed range [{min_val}, {max_val}]"
            )
        response = await f(*args, **kwargs)
        return response

    return decorated_function


def validate_query(
    query: type[BaseModel],
) -> Callable[
    [Callable[Concatenate[Request, _P], Awaitable[_T]]],
    Callable[Concatenate[Request, _P], Coroutine[Any, Any, _T]],
]:
    """Decorator for sanic query parameter validation.

    Should be removed once sanic fixes this error in their validation code.
    """

    def decorator(
        f: Callable[Concatenate[Request, _P], Awaitable[_T]],
    ) -> Callable[Concatenate[Request, _P], Coroutine[Any, Any, _T]]:
        @wraps(f)
        async def decorated_function(request: Request, *args: _P.args, **kwargs: _P.kwargs) -> _T:
            try:
                return await validate(query=query)(f)(request, *args, **kwargs)
            except KeyError as err:
                raise errors.ValidationError(message="Failed to validate the query parameters") from err

        return decorated_function

    return decorator
