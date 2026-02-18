from dataclasses import dataclass

from renku_data_services.base_models.validation import validated_json
from sanic import HTTPResponse, Request, empty, json
from sanic.response import JSONResponse
from sanic_ext import validate

from renku_data_services import base_models, errors
from renku_data_services.base_api.auth import authenticate, only_admins
from renku_data_services.base_api.blueprint import CustomBlueprint
from renku_data_services.base_api.misc import BlueprintFactoryResponse, validate_db_ids
from renku_data_services.resource_usage import apispec, model
from renku_data_services.resource_usage.db import ResourceRequestsRepo


def validate_resource_pool_limit_put(id: int, body: apispec.ResourcePoolLimitPut) -> model.ResourcePoolLimits:
    """Validate resource pool limit."""
    if body.user_limit > body.total_limit:
        raise errors.ValidationError(
            message=f"The user_limit '{body.user_limit}' must be lower than total_limit '{body.total_limit}'.",
        )
    return model.ResourcePoolLimits(id, model.Credit.from_int(body.total_limit), model.Credit.from_int(body.user_limit))


@dataclass(kw_only=True)
class ResourceUsageBP(CustomBlueprint):
    """Handlers for manipulating resource pools."""

    rr_repo: ResourceRequestsRepo
    authenticator: base_models.Authenticator

    def put_pool_limits(self) -> BlueprintFactoryResponse:
        """Set resource pool limits."""

        @authenticate(self.authenticator)
        @only_admins
        @validate_db_ids
        @validate(json=apispec.ResourcePoolLimitPut)
        async def _put(
            _: Request, user: base_models.APIUser, resource_pool_id: int, body: apispec.ResourcePoolLimitPut
        ) -> HTTPResponse:
            limits = validate_resource_pool_limit_put(resource_pool_id, body=body)
            await self.rr_repo.set_resource_pool_limits(limits)
            return empty()

        return "/resource_usage/pool_limits/<resource_pool_id>", ["PUT"], _put

    def get_pool_limits(self) -> BlueprintFactoryResponse:
        """Get resource pool limits."""

        @authenticate(self.authenticator)
        @only_admins
        @validate_db_ids
        async def _get(_: Request, user: base_models.APIUser, resource_pool_id: int) -> JSONResponse:
            result = await self.rr_repo.find_resource_pool_limits(resource_pool_id)
            if result:
                return validated_json(
                    apispec.ResourcePoolLimits,
                    apispec.ResourcePoolLimits(
                        total_limit=result.total_limit.value, user_limit=result.user_limit.value, pool_id=result.pool_id
                    )
                )
            else:
                raise errors.MissingResourceError()

        return "/resource_usage/pool_limits/<resource_pool_id>", ["GET"], _get

    def delete_pool_limits(self) -> BlueprintFactoryResponse:
        """Delete defined pool limits."""

        @authenticate(self.authenticator)
        @only_admins
        @validate_db_ids
        async def _delete(_: Request, user: base_models.APIUser, resource_pool_id: int) -> HTTPResponse:
            await self.rr_repo.delete_resource_pool_limits(resource_pool_id)
            return empty()

        return "/resource_usage/pool_limits/<resource_pool_id>", ["DELETE"], _delete
