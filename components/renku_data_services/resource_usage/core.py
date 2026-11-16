"""Core functions for resource usage."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Protocol

from renku_data_services.app_config import logging
from renku_data_services.k8s.client_interfaces import K8sClient
from renku_data_services.k8s.constants import DEFAULT_K8S_CLUSTER, ClusterId
from renku_data_services.k8s.models import GVK, K8sObject, K8sObjectFilter, K8sObjectMeta
from renku_data_services.resource_usage import apispec
from renku_data_services.resource_usage.db import ResourceRequestsRepo
from renku_data_services.resource_usage.metering import ResourceUsageMetering
from renku_data_services.resource_usage.model import (
    Credit,
    CreditBalance,
    CreditUsage,
    ResourceClassCost,
    ResourceClassCostWithPool,
    ResourceDataFacade,
    ResourcePoolLimits,
    ResourcePoolUsageLimits,
    ResourcesRequest,
    UserQuota,
)

logger = logging.getLogger(__file__)


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

    def __init__(self, repo: ResourceRequestsRepo, fetch: ResourceRequestsFetchProto) -> None:
        self._repo = repo
        self._fetch = fetch

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
        await self._repo.insert_many(result)


class ResourceUsageService:
    """Queries for resource usage and limits."""

    def __init__(self, repo: ResourceRequestsRepo, metering_client: ResourceUsageMetering | None = None) -> None:
        self._repo = repo
        self._metering_client = metering_client
        if metering_client is None:
            logger.warning(
                "No metering client configured, resource usage will not be queried from the metering service."
            )

    async def get_limits(self, resource_pool_id: int) -> ResourcePoolLimits | None:
        """Get resource pool limits.

        NOTE: Total limits are retrieved from the metering service, while user limits are retrieved from the database.
        If the resource pool does not exist, None is returned.
        """
        user_limit = await self._repo.find_user_limits(resource_pool_id)
        if user_limit is None:
            # This means the resource pool does not exist
            return None

        total_limit = CreditBalance(Credit.unlimited(), None)
        if self._metering_client is not None:
            pool_limit = await self._metering_client.get_limit(resource_pool_id)
            if pool_limit is not None:
                total_limit = CreditBalance(pool_limit.value, pool_limit.end)

        return ResourcePoolLimits(pool_id=resource_pool_id, total_limit=total_limit, user_limit=user_limit)

    async def get_usage_with_limits(
        self,
        resource_pool_id: int,
        user_id: str | None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> ResourcePoolUsageLimits | None:
        """Get resource pool usage and its limits for a given timeframe."""
        if self._metering_client is None:
            return None

        total_usage, user_usage, limits = await asyncio.gather(
            self._metering_client.get_usage(resource_pool_id, None, start_date, end_date),
            self._get_user_usage(resource_pool_id, user_id, start_date, end_date),
            self.get_limits(resource_pool_id),
        )
        if limits is None:
            return None

        return ResourcePoolUsageLimits(
            total_usage=total_usage.value,
            user_usage=user_usage.value if user_usage else None,
            pool_limits=limits,
            start_date=start_date,
            end_date=end_date,
        )

    async def _get_user_usage(
        self,
        resource_pool_id: int,
        user_id: str | None,
        start_date: datetime | None,
        end_date: datetime | None,
    ) -> CreditUsage | None:
        if self._metering_client is None or user_id is None:
            return None
        return await self._metering_client.get_usage(resource_pool_id, user_id, start_date, end_date)

    async def get_remaining_quota(self, resource_pool_id: int, user_id: str) -> CreditBalance | None:
        """Compute how many credits the user has left in the resource pool and when that amount resets.

        See get_user_quota.
        """
        quota = await self.get_user_quota(resource_pool_id, user_id)
        return quota.remaining if quota else None

    async def get_user_quota(self, resource_pool_id: int, user_id: str) -> UserQuota | None:
        """Get the quota of a user in a resource pool.

        The remaining quota is the smaller of the pool balance in the metering service and what is left
        of the weekly per-user limit. It is None when there is no limit, never an unlimited balance, so
        callers only have to deal with finite values. Returns None if there is no metering service.
        """
        if not self._metering_client:
            return None
        pool_balance, weekly_usage, weekly_limit = await asyncio.gather(
            self._metering_client.get_balance(resource_pool_id),
            self._metering_client.get_usage_of_week(resource_pool_id, user_id),
            self._repo.find_user_limits(resource_pool_id),
        )
        candidates: list[CreditBalance] = []
        if pool_balance is not None and not pool_balance.value.is_unlimited():
            candidates.append(pool_balance)
        if weekly_limit is not None and not weekly_limit.value.is_unlimited():
            candidates.append(CreditBalance(weekly_limit.value - weekly_usage.value, weekly_limit.expiry))
        remaining = min(candidates, key=lambda balance: balance.value) if candidates else None
        return UserQuota(remaining=remaining, weekly_usage=weekly_usage.value)

    @staticmethod
    def calculate_usage_hours(
        resource_class_cost: ResourceClassCostWithPool | None,
        remaining_quota: CreditBalance | None,
    ) -> tuple[float, datetime | None] | tuple[None, None]:
        """Return the remaining hours for a resource class and when they reset.

        If there is no cost for the class or no limit, (None, None) is returned.
        """
        if (
            resource_class_cost is None
            or resource_class_cost.cost.value <= 0
            or remaining_quota is None
            or remaining_quota.value.is_unlimited()
        ):
            return None, None

        remaining_hours = remaining_quota.value.value / resource_class_cost.cost.value
        return remaining_hours, remaining_quota.expiry
