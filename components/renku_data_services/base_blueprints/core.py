"""Common blueprints."""
from dataclasses import dataclass
from typing import Any, Dict

from sanic import Request, json

from renku_data_services import errors
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint


@dataclass(kw_only=True)
class MiscBP(CustomBlueprint):
    """Server contains all handlers for CRC and the configuration."""

    apispec: Dict[str, Any]
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
