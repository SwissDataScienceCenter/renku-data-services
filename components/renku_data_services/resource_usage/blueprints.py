"""Blueprint for resource usage."""

from dataclasses import dataclass
from datetime import date, datetime

from sanic import HTTPResponse, Request, empty
from sanic.response import JSONResponse
from sanic_ext import validate

from renku_data_services import base_models, errors
from renku_data_services.base_api.auth import authenticate, only_admins
from renku_data_services.base_api.blueprint import CustomBlueprint
from renku_data_services.base_api.misc import BlueprintFactoryResponse, validate_db_ids
from renku_data_services.base_models.validation import validated_json
from renku_data_services.resource_usage import apispec, model
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

    def _extract_date(self, req: Request, name: str) -> date | None:
        datestr = req.args.get(name)
        return datetime.strptime(datestr, "%Y-%m-%d") if datestr is not None else None

    def get_pool_usage(self) -> BlueprintFactoryResponse:
        """Get usage of a pool."""

        @authenticate(self.authenticator)
        @validate_db_ids
        @validate(query=apispec.ResourcePoolsResourcePoolIdUsageGetParametersQuery)
        async def _get(
            req: Request,
            user: base_models.APIUser,
            resource_pool_id: int,
            query: apispec.ResourcePoolsResourcePoolIdUsageGetParametersQuery,
        ) -> HTTPResponse:
            start_date = query.start_date
            end_date = query.end_date
            requested_by = query.user_id
            requested_by = str(requested_by) if requested_by else user.id
            if requested_by != user.id and (user.access_token is None or not user.is_admin):
                raise errors.ForbiddenError(message="You do not have the required permissions for this operation.")

            result: model.ResourcePoolUsage | None = None
            if start_date:
                result = await self.rr_svc.get_for_date(resource_pool_id, requested_by or "", start_date, end_date)
            else:
                result = await self.rr_svc.get_running_week(resource_pool_id, requested_by or "")
            if result:
                output = apispec.ResourcePoolUsage(
                    total_usage=apispec.ResourceUsageSummary(
                        runtime=result.total_usage.runtime_hours, cost=result.total_usage.cost.value
                    ),
                    pool_limits=apispec.ResourcePoolLimits(
                        pool_id=result.pool_limits.pool_id,
                        total_limit=result.pool_limits.total_limit.value,
                        user_limit=result.pool_limits.user_limit.value,
                    ),
                    user_usage=apispec.ResourceUsageSummary(
                        runtime=result.user_usage.runtime_hours, cost=result.user_usage.cost.value
                    ),
                )
                return validated_json(
                    apispec.ResourcePoolUsage,
                    output,
                )
            else:
                raise errors.MissingResourceError()

        return "/resource_pools/<resource_pool_id>/usage", ["GET"], _get
