"""Blueprint for resource usage."""

from dataclasses import dataclass

from sanic import HTTPResponse, Request, empty
from sanic.response import JSONResponse
from sanic_ext import validate

from renku_data_services import base_models, errors
from renku_data_services.base_api.auth import authenticate, only_admins
from renku_data_services.base_api.blueprint import CustomBlueprint
from renku_data_services.base_api.misc import BlueprintFactoryResponse, validate_db_ids
from renku_data_services.base_models.validation import validated_json
from renku_data_services.crc.db import ResourcePoolRepository
from renku_data_services.resource_usage import apispec
from renku_data_services.resource_usage.core import (
    ResourceUsageService,
    validate_resource_class_costs_put,
    validate_resource_pool_limit_put,
)
from renku_data_services.resource_usage.db import ResourceRequestsRepo


@dataclass(kw_only=True)
class ResourceUsageBP(CustomBlueprint):
    """Handlers for manipulating resource pools."""

    rr_repo: ResourceRequestsRepo
    rr_svc: ResourceUsageService
    rp_repo: ResourcePoolRepository
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
            result = await self.rr_repo.set_resource_pool_limits(limits)
            if not result:
                raise errors.MissingResourceError()
            else:
                return validated_json(apispec.ResourcePoolLimitPut, body)

        return "/resource_pools/<resource_pool_id>/limits", ["PUT"], _put

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
                    ),
                )
            else:
                raise errors.MissingResourceError()

        return "/resource_pools/<resource_pool_id>/limits", ["GET"], _get

    def delete_pool_limits(self) -> BlueprintFactoryResponse:
        """Delete defined pool limits."""

        @authenticate(self.authenticator)
        @only_admins
        @validate_db_ids
        async def _delete(_: Request, user: base_models.APIUser, resource_pool_id: int) -> HTTPResponse:
            await self.rr_repo.delete_resource_pool_limits(resource_pool_id)
            return empty()

        return "/resource_pools/<resource_pool_id>/limits", ["DELETE"], _delete

    def put_class_costs(self) -> BlueprintFactoryResponse:
        """Set resource class cost."""

        @authenticate(self.authenticator)
        @only_admins
        @validate_db_ids
        @validate(json=apispec.ResourceClassCostPut)
        async def _put(
            _: Request,
            user: base_models.APIUser,
            resource_pool_id: int,
            class_id: int,
            body: apispec.ResourceClassCostPut,
        ) -> HTTPResponse:
            costs = validate_resource_class_costs_put(class_id, body=body)
            result = await self.rr_repo.set_resource_class_costs(costs)
            if not result:
                raise errors.MissingResourceError()
            else:
                return validated_json(apispec.ResourceClassCostPut, body)

        return "/resource_pools/<resource_pool_id>/classes/<class_id>/cost", ["PUT"], _put

    def get_class_cost(self) -> BlueprintFactoryResponse:
        """Get resource class costs."""

        @authenticate(self.authenticator)
        @only_admins
        @validate_db_ids
        async def _get(_: Request, user: base_models.APIUser, resource_pool_id: int, class_id: int) -> JSONResponse:
            result = await self.rr_repo.find_resource_class_costs(resource_pool_id, class_id)
            if result:
                return validated_json(
                    apispec.ResourceClassCost,
                    apispec.ResourceClassCost(
                        resource_pool_id=resource_pool_id, resource_class_id=class_id, cost=result.cost.value
                    ),
                )
            else:
                raise errors.MissingResourceError()

        return "/resource_pools/<resource_pool_id>/classes/<class_id>/cost", ["GET"], _get

    def delete_class_cost(self) -> BlueprintFactoryResponse:
        """Delete resource class costs limits."""

        @authenticate(self.authenticator)
        @only_admins
        @validate_db_ids
        async def _delete(_: Request, user: base_models.APIUser, resource_pool_id: int, class_id: int) -> HTTPResponse:
            await self.rr_repo.delete_resource_class_costs(class_id)
            return empty()

        return "/resource_pools/<resource_pool_id>/classes/<class_id>/cost", ["DELETE"], _delete

    def get_pool_usage(self) -> BlueprintFactoryResponse:
        """Get usage of a pool."""

        @authenticate(self.authenticator)
        @only_admins
        @validate_db_ids
        @validate(query=apispec.ResourcePoolsResourcePoolIdUsageGetParametersQuery)
        async def _get(
            req: Request,
            user: base_models.APIUser,
            resource_pool_id: int,
            query: apispec.ResourcePoolsResourcePoolIdUsageGetParametersQuery,
        ) -> HTTPResponse:
            # Validate that the resource pool exists and the user has access to it
            await self.rp_repo.get_resource_pool(api_user=user, resource_pool_id=resource_pool_id)

            result = await self.rr_svc.get_usage_timeframe_with_limits(
                resource_pool_id, query.user_id, query.start_date, query.end_date
            )
            if result:
                output = apispec.ResourcePoolUsageLimits(
                    total_usage=result.total_usage.value,
                    pool_limits=apispec.ResourcePoolLimits(
                        pool_id=result.pool_limits.pool_id,
                        total_limit=result.pool_limits.total_limit.value,
                        user_limit=result.pool_limits.user_limit.value,
                    ),
                    user_usage=result.user_usage.value if result.user_usage is not None else None,
                    start_date=result.start_date,
                    end_date=result.end_date,
                )
                return validated_json(
                    apispec.ResourcePoolUsageLimits,
                    output,
                )
            else:
                raise errors.MissingResourceError(
                    message=f"Usage tracking for resource pool ID {resource_pool_id} is not available"
                )

        return "/resource_pools/<resource_pool_id>/usage", ["GET"], _get
