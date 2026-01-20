from collections.abc import Callable
from datetime import datetime
from typing import AsyncIterator, cast

import sqlalchemy.sql as sa
from sqlalchemy.ext.asyncio import AsyncScalarResult, AsyncSession
from ulid import ULID

from renku_data_services.app_config import logging
from renku_data_services.k8s.client_interfaces import K8sClient
from renku_data_services.k8s.clients import K8sClusterClientsPool
from renku_data_services.k8s.constants import DEFAULT_K8S_CLUSTER, ClusterId
from renku_data_services.k8s.models import GVK, K8sObjectFilter, K8sObjectMeta
from renku_data_services.resource_usage.model import (
    ResourceDataFacade,
    ResourcesRequest,
)
from renku_data_services.resource_usage.orm import ResourceRequestsLogORM

logger = logging.getLogger(__file__)


class ResourceRequestsRepo:
    """Repository for resource requests data."""

    def __init__(self, session_maker: Callable[..., AsyncSession]) -> None:
        self.session_maker = session_maker

    async def find_all(self, chunk_size: int = 100) -> AsyncIterator[ResourceRequestsLogORM]:
        """Select all records."""
        stmt = sa.select(ResourceRequestsLogORM).order_by(ResourceRequestsLogORM.capture_date.desc())
        async with self.session_maker() as session:
            result = await session.stream(stmt.execution_options(yield_per=chunk_size))
            async for e in result.scalars():
                yield e

    async def insertOne(self, req: ResourcesRequest) -> None:
        """Insert one data into the log."""
        async with self.session_maker() as session, session.begin():
            obj = ResourceRequestsLogORM(
                cluster_id=cast(ULID, req.cluster_id) if req.cluster_id else None,
                namespace=req.namespace,
                pod_name=req.pod_name,
                capture_date=req.capture_date,
                user_id=req.user_id,
                project_id=req.project_id,
                launcher_id=req.launcher_id,
                cpu_request=req.data.cpu.cores,
                memory_request=req.data.memory.bytes,
                gpu_request=req.data.gpu.cores if req.data.gpu else 0,
            )
            session.add(obj)
            await session.flush()


class ResourceRequestsFetch:
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

        date = datetime.now().replace(microsecond=0)
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

    def __init__(self, repo: ResourceRequestsRepo, fetch: ResourceRequestsFetch) -> None:
        self._repo = repo
        self._fetch = fetch

    async def record_resource_requests(self, namespace: str, with_labels: dict[str, str] | None = None) -> None:
        """Fetches all resource requests in the given namespace and stores them."""
        result = await self._fetch.get_resources_requests(namespace, with_labels)
        for v in result.values():
            await self._repo.insertOne(v)
