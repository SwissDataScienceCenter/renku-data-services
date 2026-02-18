from dataclasses import dataclass

from sanic import HTTPResponse, Request, empty, json
from sanic_ext import validate

from renku_data_services import base_models, errors
from renku_data_services.base_api.auth import authenticate, only_admins
from renku_data_services.base_api.blueprint import CustomBlueprint
from renku_data_services.base_api.misc import BlueprintFactoryResponse
from renku_data_services.resource_usage import apispec, model
from renku_data_services.resource_usage.db import ResourceRequestsRepo


def validate_resource_pool_limit_put(id: int, body: apispec.ResourcePoolLimitPut) -> model.ResourcePoolLimits:
    """Validate resource pool limit."""
    if body.user_limit > body.total_limit:
        raise errors.ValidationError(
            message=f"The user_limit '{body.user_limit}' must be lower than total_limit '{body.total_limit}f'.",
        )
    return model.ResourcePoolLimits(id, model.Credit.from_int(body.total_limit), model.Credit.from_int(body.user_limit))


@dataclass(kw_only=True)
class ResourceUsageBP(CustomBlueprint):
    """Handlers for manipulating resource pools."""

    rr_repo: ResourceRequestsRepo
    authenticator: base_models.Authenticator

    def put(self) -> BlueprintFactoryResponse:
        """Set resource pool limits."""

        @authenticate(self.authenticator)
        @only_admins
        @validate(json=apispec.ResourcePoolLimitPut)
        async def _put(
            _: Request, user: base_models.APIUser, resource_pool_id: int, body: apispec.ResourcePoolLimitPut
        ) -> HTTPResponse:
            limits = validate_resource_pool_limit_put(resource_pool_id, body=body)
            await self.rr_repo.set_resource_pool_limits(limits)
            return empty()

        return "/resource_usage/pool_limits/<pool_id>", ["PUT"], _put

    def get(self) -> BlueprintFactoryResponse:
        """Get resource pool limits."""

        @authenticate(self.authenticator)
        @only_admins
        async def _get(_: Request, user: base_models.APIUser, pool_id: int) -> HTTPResponse:
            result = await self.rr_repo.find_resource_pool_limits(pool_id)
            if result:
                return json(
                    apispec.ResourcePoolLimits(
                        total_limit=result.total_limit.value, user_limit=result.user_limit.value, pool_id=result.pool_id
                    )
                )
            else:
                raise errors.MissingResourceError()

        return "/resource_usage/pool_limits/<pool_id>", ["GET"], _get
