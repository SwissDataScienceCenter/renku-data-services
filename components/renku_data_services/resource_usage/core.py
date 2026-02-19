"""Core functions for resource usage."""

from datetime import UTC, datetime, timedelta
from typing import Protocol

from renku_data_services.app_config import logging
from renku_data_services.k8s.client_interfaces import K8sClient
from renku_data_services.k8s.constants import DEFAULT_K8S_CLUSTER, ClusterId
from renku_data_services.k8s.models import GVK, K8sObjectFilter, K8sObjectMeta
from renku_data_services.resource_usage.db import ResourceRequestsRepo
from renku_data_services.resource_usage.model import (
    ResourceDataFacade,
    ResourcePoolUsage,
    ResourcesRequest,
    ResourceUsageQuery,
    ResourceUsageSummary,
)

logger = logging.getLogger(__file__)


class ResourceRequestsFetchProto(Protocol):
    """Protocol defining methods for getting resource requests."""

    async def get_resources_requests(self, capture_interval: timedelta) -> dict[str, ResourcesRequest]:
        """Return the resources requests of all pods and pvcs."""
        ...


class ResourceRequestsFetch(ResourceRequestsFetchProto):
    """Get resource request data."""

    def __init__(self, k8s_client: K8sClient) -> None:
        self._client = k8s_client

    async def get_resources_requests(self, capture_interval: timedelta) -> dict[str, ResourcesRequest]:
        """Return the resources requests of all pods and pvcs."""

        logger.debug("Get pods and pvc from all clusters")

        date = datetime.now(UTC).replace(microsecond=0)
        result: dict[str, ResourcesRequest] = {}

        pod_filter = K8sObjectFilter(gvk=GVK(kind="pod", version="v1"))
        pvc_filter = K8sObjectFilter(gvk=GVK(kind="PersistentVolumeClaim", version="v1"))

        node_cache: dict[str, ResourceDataFacade] = {}

        async def get_node(name: str | None) -> ResourceDataFacade | None:
            if name:
                node_obj = node_cache.get(name)
                if node_obj is not None:
                    return node_obj
                else:
                    pod_node = await self._client.get(
                        K8sObjectMeta(
                            name=name, namespace=pod.namespace, cluster=pod.cluster, gvk=GVK(kind="node", version="v1")
                        )
                    )
                    if pod_node:
                        node_obj = ResourceDataFacade(pod_node)
                        node_cache[name] = node_obj
                        return node_obj
            return None

        async for pod in self._client.list(pod_filter):
            obj = ResourceDataFacade(obj=pod)
            node_obj: ResourceDataFacade | None = None
            try:
                node_obj = await get_node(obj.node_name)
            except Exception as ex:
                logger.debug(f"Cannot get node (ignoring): {ex}", exc_info=ex)
                node_obj = None

            rreq = ResourcesRequest.from_pod_and_node(obj, node_obj, pod.cluster, date, capture_interval)
            await self._amend_session_fallback(pod.cluster, obj, rreq)
            nreq = rreq.add(result.get(rreq.id, rreq.to_empty()))
            result.update({nreq.id: nreq})

        if result == {}:
            logger.warning("Empty list returned when listing pods!")

        async for pvc in self._client.list(pvc_filter):
            obj = ResourceDataFacade(obj=pvc)
            rreq = ResourcesRequest.from_pvc(obj, pvc.cluster, date, capture_interval)
            await self._amend_session_fallback(pvc.cluster, obj, rreq)
            nreq = rreq.add(result.get(rreq.id, rreq.to_empty()))
            result.update({nreq.id: nreq})

        if result == {}:
            logger.warning("Empty list returned when listing pvcs!")

        return result

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


class ResourcesRequestRecorder:
    """Methods for recording resource requests."""

    def __init__(self, repo: ResourceRequestsRepo, fetch: ResourceRequestsFetchProto) -> None:
        self._repo = repo
        self._fetch = fetch

    async def record_resource_requests(self, interval: timedelta) -> None:
        """Fetches all resource requests in the given namespace and stores them."""
        result = await self._fetch.get_resources_requests(interval)
        size = len(result)
        if size == 0:
            logger.warning("No pod or pvc was found!")
        else:
            logger.info(f"Inserting {size} resource request records.")
        await self._repo.insert_many(result.values())


class ResourceUsageService:
    """Queries for resource usages."""

    def __init__(self, repo: ResourceRequestsRepo) -> None:
        self._repo = repo

    async def usage_of_running_week(
        self, resource_pool_id: int, user_id: str | None, current_time: datetime | None = None
    ) -> ResourceUsageSummary:
        """Return the resource usage for the given pool of the currently running week.

        The week start is Monday 0:00 UTC. Resource usage is returned in 'credits'. When a user_id
        is given, the results represent the usage of only that user. Otherwise the overall pool usage
        is returned. The running week is calculated from the `current_time` argument, which is the current
        time if not specified.
        """
        now = current_time.replace(tzinfo=UTC) if current_time is not None else datetime.now(UTC)
        start = (now - timedelta(days=now.weekday())).date()
        query = ResourceUsageQuery(since=start, until=now.date(), user_id=user_id, resource_pool_id=resource_pool_id)
        result = ResourceUsageSummary.empty()
        async for item in self._repo.find_usage(query):
            result = result.add(item)

        return result

    async def get_running_week(
        self, resource_pool_id: int, user_id: str, current_time: datetime | None = None
    ) -> ResourcePoolUsage | None:
        """Get resource pool usage and its limits."""

        limits = await self._repo.find_resource_pool_limits(resource_pool_id)

        if limits:
            user_usage = await self.usage_of_running_week(resource_pool_id, user_id, current_time)
            total_usage = await self.usage_of_running_week(resource_pool_id, None, current_time)
            return ResourcePoolUsage(total_usage, user_usage, limits)
        else:
            return None
