"""Common blueprints."""
from dataclasses import dataclass
from functools import wraps
from typing import Any

from sanic import Request, json

from renku_data_services import errors
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint


@dataclass(kw_only=True)
class MiscBP(CustomBlueprint):
    """Server contains all handlers for CRC and the configuration."""

    apispec: dict[str, Any]
    version: str

    def get_apispec(self) -> BlueprintFactoryResponse:
        """Servers the OpenAPI specification."""

        async def _get_apispec(_: Request):
            return json(self.apispec)

        return "/spec.json", ["GET"], _get_apispec

    def get_error(self) -> BlueprintFactoryResponse:
        """Returns a sample error response."""

        async def _get_error(_: Request):
            raise errors.ValidationError(message="Sample validation error")

        return "/error", ["GET"], _get_error

    def get_version(self) -> BlueprintFactoryResponse:
        """Returns the version."""

        async def _get_version(_: Request):
            return json({"version": self.version})

        return "/version", ["GET"], _get_version


def validate_db_ids(f):
    """Decorator for a Sanic handler that errors out if passed in IDs are outside of the valid range for postgres."""

    @wraps(f)
    async def decorated_function(*args, **kwargs):
        resource_pool_id = kwargs.get("resource_pool_id")
        class_id = kwargs.get("class_id")
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
