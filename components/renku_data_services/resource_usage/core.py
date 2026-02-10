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
    ResourcesRequest,
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
            node_obj: ResourceDataFacade | None = await get_node(obj.node_name)

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
