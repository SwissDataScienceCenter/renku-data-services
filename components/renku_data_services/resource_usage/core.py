"""Core functions for resource usage."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Protocol

from renku_data_services import errors
from renku_data_services.app_config import logging
from renku_data_services.base_models.core import InternalServiceAdmin, ServiceAdminId
from renku_data_services.k8s.client_interfaces import K8sClient
from renku_data_services.k8s.constants import DEFAULT_K8S_CLUSTER, ClusterId
from renku_data_services.k8s.models import GVK, K8sObject, K8sObjectFilter, K8sObjectMeta
from renku_data_services.resource_usage import apispec
from renku_data_services.resource_usage.db import ResourceRequestsRepo
from renku_data_services.resource_usage.metering import MetricCode, ResourceUsageMetering
from renku_data_services.resource_usage.model import (
    Credit,
    ResourceClassCost,
    ResourceDataFacade,
    ResourcePoolLimits,
    ResourcePoolUsageLimits,
    ResourcesRequest,
)

if TYPE_CHECKING:
    from renku_data_services.crc.db import ResourcePoolQueryRepository

logger = logging.getLogger(__file__)


def validate_resource_pool_limit_put(id: int, body: apispec.ResourcePoolLimitPut) -> ResourcePoolLimits:
    """Validate resource pool limit."""
    if body.user_limit > body.total_limit:
        raise errors.ValidationError(
            message=f"The user_limit '{body.user_limit}' must be lower than total_limit '{body.total_limit}'.",
        )
    return ResourcePoolLimits(id, Credit.from_int(body.total_limit), Credit.from_int(body.user_limit))


def validate_resource_class_costs_put(class_id: int, body: apispec.ResourceClassCostPut) -> ResourceClassCost:
    """Validate the resource class cost data."""
    return ResourceClassCost(resource_class_id=class_id, cost=Credit.from_int(body.cost))


class ResourceRequestsFetchProto(Protocol):
    """Protocol defining methods for getting resource requests."""

    def get_resources_requests_iter(self, capture_interval: timedelta) -> AsyncIterator[ResourcesRequest]:
        """Iterating through resource requests."""
        ...


class ResourceRequestsFetch(ResourceRequestsFetchProto):
    """Get resource request data."""

    def __init__(self, k8s_client: K8sClient) -> None:
        self._client = k8s_client

    async def _get_node(
        self, node_name: str | None, pod: K8sObject, node_cache: dict[str, ResourceDataFacade]
    ) -> ResourceDataFacade | None:
        if node_name:
            node_obj = node_cache.get(node_name)
            if node_obj is not None:
                return node_obj
            else:
                pod_node = await self._client.get(
                    K8sObjectMeta(
                        name=node_name, namespace=pod.namespace, cluster=pod.cluster, gvk=GVK(kind="node", version="v1")
                    )
                )
                if pod_node:
                    node_obj = ResourceDataFacade(pod_node)
                    node_cache[node_name] = node_obj
                    return node_obj
        return None

    async def get_resources_requests_iter(self, capture_interval: timedelta) -> AsyncIterator[ResourcesRequest]:
        """Iterating through resource requests.

        NOTE: Users of the resource requests log populated by this method expect the following:
        - One row (i.e. one item from the iterator) measures all resources that are available for a
          specific timespan and a specific uid. For example, for a Pod, each row contains its cpu,
          memory and gpu. If these were measured in separate rows for the exact same Pod calculating usage would break.
        - When the resource requests change from a value to NULL or vice versa, then the uid changes.
          This is unlikely to occur in Kubernetes but manipulating the data after it has been collected
          could cause such a scenario to occur.
        """

        logger.debug("Get pods and pvc from all clusters")

        date = datetime.now(UTC).replace(microsecond=0)
        pod_filter = K8sObjectFilter(
            gvk=GVK(kind="Pod", version="v1"), label_selector={"app.kubernetes.io/name": "AmaltheaSession"}
        )
        pvc_filter = K8sObjectFilter(gvk=GVK(kind="PersistentVolumeClaim", version="v1"))
        node_cache: dict[str, ResourceDataFacade] = {}
        async for pod in self._client.list(pod_filter):
            obj = ResourceDataFacade(obj=pod)
            node_obj: ResourceDataFacade | None = None
            try:
                node_obj = await self._get_node(obj.node_name, pod, node_cache)
            except Exception as ex:
                logger.debug(f"Cannot get node (ignoring): {ex}", exc_info=ex)
                node_obj = None

            rreq = ResourcesRequest.from_pod_and_node(obj, node_obj, pod.cluster, date, capture_interval)
            await self._amend_session_fallback(pod.cluster, obj, rreq)
            yield rreq

        async for pvc in self._client.list(pvc_filter):
            obj = ResourceDataFacade(obj=pvc)
            rreq = ResourcesRequest.from_pvc(obj, pvc.cluster, date, capture_interval)
            await self._amend_session_fallback(pvc.cluster, obj, rreq)
            yield rreq

    async def _amend_session_fallback(
        self, cluster_id: ClusterId | None, obj: ResourceDataFacade, rreq: ResourcesRequest
    ) -> None:
        """Modifies the argument with data retrieved from the amalthea session if applicable."""

        if not rreq.user_id and obj.session_instance_id:
            ams = await self._client.get(
                K8sObjectMeta(
                    name=obj.session_instance_id,
                    namespace=obj.namespace,
                    cluster=cluster_id or DEFAULT_K8S_CLUSTER,
                    gvk=GVK(kind="AmaltheaSession", version="v1"),
                )
            )
            if ams:
                amsObj = ResourceDataFacade(ams)
                rreq.user_id = rreq.user_id or amsObj.user_id
                rreq.project_id = rreq.project_id or amsObj.project_id
                rreq.launcher_id = rreq.launcher_id or amsObj.launcher_id
                if not rreq.resource_class_id:
                    rreq.resource_class_id = amsObj.resource_class_id
                if not rreq.resource_pool_id:
                    rreq.resource_pool_id = amsObj.resource_pool_id


class ResourcesRequestRecorder(Protocol):
    """Methods for recording resource requests."""

    async def record_resource_requests(self, interval: timedelta) -> None:
        """Fetches all resource requests in the given namespace and stores them."""
        ...


class NoopResourcesRequestRecorder(ResourcesRequestRecorder):
    """No-op resource request recorder."""

    async def record_resource_requests(self, interval: timedelta) -> None:
        """Fetches all resource requests in the given namespace and stores them."""
        return None


class DefaultResourcesRequestRecorder(ResourcesRequestRecorder):
    """Methods for recording resource requests."""

    def __init__(
        self,
        requests_repo: ResourceRequestsRepo,
        pool_repo: ResourcePoolQueryRepository,
        fetch: ResourceRequestsFetchProto,
        metering: ResourceUsageMetering | None = None,
    ) -> None:
        self._requests_repo = requests_repo
        self._pool_repo = pool_repo
        self._fetch = fetch
        self._metering = metering

    async def record_resource_requests(self, interval: timedelta) -> None:
        """Fetches all resource requests in the given namespace and stores them."""
        result: list[ResourcesRequest] = []  # await self._fetch.get_resources_requests(interval)
        async for item in self._fetch.get_resources_requests_iter(interval):
            result.append(item)
        size = len(result)
        if size == 0:
            logger.warning("No pod or pvc was found!")
        else:
            logger.info(f"Inserting {size} resource request records.")
        await self._requests_repo.insert_many(result)
        if self._metering is not None:
            class_ids = {r.resource_class_id for r in result if r.resource_class_id is not None}
            costs = await self._requests_repo.get_costs_by_class_ids(class_ids)
            admin_user = InternalServiceAdmin(id=ServiceAdminId.capacity_reservation)
            classes = await self._pool_repo.get_classes_by_class_ids(admin_user, list(class_ids))
            classes_dict = {c.id: c for c in classes}
            await self._metering.emit(result, costs, classes_dict, MetricCode.session_resource_usage)


class ResourceUsageService:
    """Queries for resource usage and limits."""

    def __init__(self, repo: ResourceRequestsRepo | None, metering_client: ResourceUsageMetering | None = None) -> None:
        self._repo = repo
        self._metering_client = metering_client
        if metering_client is None:
            logger.warning(
                "No metering client configured, resource usage will not be queried from the metering service."
            )

    async def get_default_limits(self, resource_pool_id: int) -> ResourcePoolLimits:
        """Get default resource pool limits."""
        if self._repo is not None:
            db_limits = await self._repo.find_resource_pool_limits(resource_pool_id)
            if db_limits is not None:
                return db_limits

        return ResourcePoolLimits(
            pool_id=resource_pool_id,
            total_limit=Credit.unlimited(),
            user_limit=Credit.unlimited(),
        )

    async def get_limits(self, resource_pool_id: int) -> ResourcePoolLimits:
        """Get resource pool limits."""
        default_limits = await self.get_default_limits(resource_pool_id)
        if self._metering_client is None:
            return default_limits

        total_limit = await self._metering_client.get_resource_pool_total_limit(resource_pool_id)
        return ResourcePoolLimits(
            pool_id=resource_pool_id,
            total_limit=total_limit,
            user_limit=default_limits.user_limit,  # NOTE: The metering service does not provide user limits
        )

    async def get_usage_with_limits(
        self,
        resource_pool_id: int,
        user_id: str | None,
    ) -> ResourcePoolUsageLimits | None:
        """Get current resource pool usage and its limits."""
        if self._metering_client is None:
            return None

        try:
            usage, limits = await asyncio.gather(
                self._metering_client.get_current_usage(resource_pool_id, user_id),
                self.get_limits(resource_pool_id),
            )
            return ResourcePoolUsageLimits(
                total_usage=usage.total_usage,
                user_usage=usage.user_usage,
                pool_limits=limits,
                start_date=usage.start_date,
                end_date=usage.end_date,
            )
        except errors.ThirdPartyAPIError as e:
            logger.error(f"Error querying compute usage with limits: {e}")
            return None

    async def get_usage_timeframe_with_limits(
        self,
        resource_pool_id: int,
        user_id: str | None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> ResourcePoolUsageLimits | None:
        """Get resource pool usage and its limits for a given timeframe."""
        if self._metering_client is None:
            return None

        usage, limits = await asyncio.gather(
            self._metering_client.get_usage_timeframe(resource_pool_id, user_id, start_date, end_date),
            self.get_limits(resource_pool_id),
        )
        return ResourcePoolUsageLimits(
            total_usage=usage.total_usage,
            user_usage=usage.user_usage,
            pool_limits=limits,
            start_date=usage.start_date,
            end_date=usage.end_date,
        )

    def get_remaining_quota(self, usage: ResourcePoolUsageLimits | None) -> float | None:
        """Compute the remaining quota based on the usage and limits."""
        if usage is None:
            return None

        user_limit = usage.pool_limits.user_limit
        total_limit = usage.pool_limits.total_limit
        if user_limit.is_unlimited() or usage.user_usage is None:
            remaining_user_quota = float("inf")
        else:
            remaining_user_quota = user_limit.value - usage.user_usage.value
        if total_limit.is_unlimited():
            remaining_total_quota = float("inf")
        else:
            remaining_total_quota = total_limit.value - usage.total_usage.value

        if remaining_user_quota == float("inf") and remaining_total_quota == float("inf"):
            return None

        return min(remaining_user_quota, remaining_total_quota)
