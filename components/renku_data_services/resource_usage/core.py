from datetime import UTC, datetime
from typing import Protocol

from renku_data_services.app_config import logging
from renku_data_services.k8s.client_interfaces import K8sClient
from renku_data_services.k8s.clients import K8sClusterClientsPool
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

    async def get_resources_requests(
        self, namespace: str, with_labels: dict[str, str] | None = None
    ) -> dict[str, ResourcesRequest]:
        """Return the resources requests of all pods."""
        ...


class ResourceRequestsFetch(ResourceRequestsFetchProto):
    """Get resource request data."""

    def __init__(self, k8s_client: K8sClient) -> None:
        self._client = k8s_client

    async def get_resources_requests(
        self, namespace: str, with_labels: dict[str, str] | None = None
    ) -> dict[str, ResourcesRequest]:
        """Return the resources requests of all pods."""

        clusters: list[ClusterId | None] = []
        if isinstance(self._client, K8sClusterClientsPool):
            clusters = [e.get_cluster().id for e in self._client.get_clients()]

        if clusters == []:
            clusters = [None]

        logger.debug(f"Get pods from clusters {clusters} (size={len(clusters)})")

        date = datetime.now(UTC).replace(microsecond=0)
        result: dict[str, ResourcesRequest] = {}

        for cluster_id in clusters:
            async for pod in self._client.list(
                K8sObjectFilter(
                    gvk=GVK(kind="pod", version="v1"),
                    namespace=namespace,
                    label_selector=with_labels,
                    cluster=cluster_id,
                )
            ):
                obj = ResourceDataFacade(pod=pod)
                rreq = obj.to_resources_request(cluster_id, date)
                await self._amend_session_fallback(cluster_id, obj, rreq)

                nreq = rreq.add(result.get(rreq.id, rreq.to_zero()))
                result.update({nreq.id: nreq})

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

    async def record_resource_requests(self, namespace: str, with_labels: dict[str, str] | None = None) -> None:
        """Fetches all resource requests in the given namespace and stores them."""
        result = await self._fetch.get_resources_requests(namespace, with_labels)
        await self._repo.insert_many(result.values())
