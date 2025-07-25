"""K8s watcher main."""

from __future__ import annotations

import asyncio
import contextlib
from asyncio import CancelledError, Task
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from renku_data_services.app_config import logging
from renku_data_services.base_models.core import APIUser, InternalServiceAdmin, ServiceAdminId
from renku_data_services.base_models.metrics import MetricsService
from renku_data_services.crc.db import ResourcePoolRepository
from renku_data_services.k8s.clients import K8sClusterClient
from renku_data_services.k8s.models import GVK, K8sObject, K8sObjectFilter
from renku_data_services.k8s_watcher.db import K8sDbCache
from renku_data_services.notebooks.crs import State

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from renku_data_services.k8s.constants import ClusterId
    from renku_data_services.k8s.models import APIObjectInCluster, Cluster

type EventHandler = Callable[[APIObjectInCluster, str], Awaitable[None]]
type SyncFunc = Callable[[], Awaitable[None]]

k8s_watcher_admin_user = InternalServiceAdmin(id=ServiceAdminId.k8s_watcher)


class K8sWatcher:
    """Watch k8s events and call the handler with every event."""

    def __init__(
        self,
        handler: EventHandler,
        clusters: dict[ClusterId, Cluster],
        kinds: list[GVK],
        db_cache: K8sDbCache,
    ) -> None:
        self.__handler = handler
        self.__watch_tasks: dict[ClusterId, list[Task]] = {}
        self.__full_sync_tasks: dict[ClusterId, Task] = {}
        self.__full_sync_times: dict[ClusterId, datetime] = {}
        self.__full_sync_running: set[ClusterId] = set()
        self.__kinds = kinds
        self.__clusters = clusters
        self.__sync_period_seconds = 600
        self.__cache = db_cache

    async def __sync(self, cluster: Cluster, kind: GVK) -> None:
        """Upsert K8s objects in the cache and remove deleted objects from the cache."""
        clnt = K8sClusterClient(cluster)
        fltr = K8sObjectFilter(gvk=kind, cluster=cluster.id, namespace=cluster.namespace)
        # Upsert new / updated objects
        objects_in_k8s: dict[str, K8sObject] = {}
        async for obj in clnt.list(fltr):
            objects_in_k8s[obj.name] = obj
            await self.__cache.upsert(obj)
        # Remove objects that have been deleted from k8s but are still in cache
        async for cache_obj in self.__cache.list(fltr):
            cache_obj_is_in_k8s = objects_in_k8s.get(cache_obj.name) is not None
            if cache_obj_is_in_k8s:
                continue
            await self.__cache.delete(cache_obj)

    async def __full_sync(self, cluster: Cluster) -> None:
        """Run the full sync if it has never run or at the required interval."""
        last_sync = self.__full_sync_times.get(cluster.id)
        since_last_sync = datetime.now() - last_sync if last_sync is not None else None
        if since_last_sync is not None and since_last_sync.total_seconds() < self.__sync_period_seconds:
            return
        self.__full_sync_running.add(cluster.id)
        for kind in self.__kinds:
            logger.info(f"Starting full k8s cache sync for cluster {cluster} and kind {kind}")
            await self.__sync(cluster, kind)
        self.__full_sync_times[cluster.id] = datetime.now()
        self.__full_sync_running.remove(cluster.id)

    async def __periodic_full_sync(self, cluster: Cluster) -> None:
        """Keeps trying to run the full sync."""
        while True:
            await self.__full_sync(cluster)
            await asyncio.sleep(self.__sync_period_seconds / 10)

    async def __watch_kind(self, kind: GVK, cluster: Cluster) -> None:
        while True:
            try:
                watch = cluster.api.async_watch(kind=kind.kr8s_kind, namespace=cluster.namespace)
                async for event_type, obj in watch:
                    while cluster.id in self.__full_sync_running:
                        logger.info(
                            f"Pausing k8s watch event processing for cluster {cluster} until full sync completes"
                        )
                        await asyncio.sleep(5)
                    await self.__handler(cluster.with_api_object(obj), event_type)
                    # in some cases, the kr8s loop above just never yields, especially if there's exceptions which
                    # can bypass async scheduling. This sleep here is as a last line of defence so this code does not
                    # execute indefinitely and prevent another resource kind from being watched.
                    await asyncio.sleep(0)
            except Exception as e:
                logger.error(f"watch loop failed for {kind} in cluster {cluster.id}", exc_info=e)
                # without sleeping, this can just hang the code as exceptions seem to bypass the async scheduler
                await asyncio.sleep(1)
                pass

    def __run_single(self, cluster: Cluster) -> list[Task]:
        # The loops and error handling here will need some testing and love
        tasks = []
        for kind in self.__kinds:
            logger.info(f"watching {kind} in cluster {cluster.id}")
            tasks.append(asyncio.create_task(self.__watch_kind(kind, cluster)))

        return tasks

    async def start(self) -> None:
        """Start the watcher."""
        for cluster in sorted(self.__clusters.values(), key=lambda x: x.id):
            await self.__full_sync(cluster)
            self.__full_sync_tasks[cluster.id] = asyncio.create_task(self.__periodic_full_sync(cluster))
            self.__watch_tasks[cluster.id] = self.__run_single(cluster)

    async def wait(self) -> None:
        """Wait for all tasks.

        This is mainly used to block the main function.
        """
        all_tasks = list(self.__full_sync_tasks.values())
        for tasks in self.__watch_tasks.values():
            all_tasks.extend(tasks)
        await asyncio.gather(*all_tasks)

    async def stop(self, timeout: timedelta = timedelta(seconds=10)) -> None:
        """Stop the watcher or timeout."""

        async def stop_task(task: Task, timeout: timedelta) -> None:
            if task.done():
                return
            task.cancel()
            try:
                async with asyncio.timeout(timeout.total_seconds()):
                    with contextlib.suppress(CancelledError):
                        await task
            except TimeoutError:
                logger.error("timeout trying to cancel k8s watcher task")
                return

        for task_list in self.__watch_tasks.values():
            for task in task_list:
                await stop_task(task, timeout)
        for task in self.__full_sync_tasks.values():
            await stop_task(task, timeout)


async def collect_metrics(
    previous_obj: K8sObject | None,
    new_obj: APIObjectInCluster,
    event_type: str,
    user_id: str,
    metrics: MetricsService,
    rp_repo: ResourcePoolRepository,
) -> None:
    """Track product metrics."""
    user = APIUser(id=user_id)

    if event_type == "DELETED":
        # session stopping
        await metrics.session_stopped(user=user, metadata={"session_id": new_obj.meta.name})
        return
    previous_state = previous_obj.manifest.get("status", {}).get("state", None) if previous_obj else None
    match new_obj.obj.status.state:
        case State.Running.value if previous_state is None or previous_state == State.NotReady.value:
            # session starting
            resource_class_id = int(new_obj.obj.metadata.annotations.get("renku.io/resource_class_id"))
            resource_pool = await rp_repo.get_resource_pool_from_class(k8s_watcher_admin_user, resource_class_id)
            resource_class = await rp_repo.get_resource_class(k8s_watcher_admin_user, resource_class_id)

            await metrics.session_started(
                user=user,
                metadata={
                    "cpu": int(resource_class.cpu * 1000),
                    "memory": resource_class.memory,
                    "gpu": resource_class.gpu,
                    "storage": new_obj.obj.spec.session.storage.size,
                    "resource_class_id": resource_class_id,
                    "resource_pool_id": resource_pool.id or "",
                    "resource_class_name": f"{resource_pool.name}.{resource_class.name}",
                    "session_id": new_obj.meta.name,
                },
            )
        case State.Running.value | State.NotReady.value if previous_state == State.Hibernated.value:
            # session resumed
            await metrics.session_resumed(user, metadata={"session_id": new_obj.meta.name})
        case State.Hibernated.value if previous_state != State.Hibernated.value:
            # session hibernated
            await metrics.session_hibernated(user=user, metadata={"session_id": new_obj.meta.name})
        case _:
            pass


def k8s_object_handler(cache: K8sDbCache, metrics: MetricsService, rp_repo: ResourcePoolRepository) -> EventHandler:
    """Listens and to k8s events and updates the cache."""

    async def handler(obj: APIObjectInCluster, event_type: str) -> None:
        existing = await cache.get(obj.meta)
        if obj.user_id is not None:
            try:
                await collect_metrics(existing, obj, event_type, obj.user_id, metrics, rp_repo)
            except Exception as e:
                logger.error("failed to track product metrics", exc_info=e)
        if event_type == "DELETED":
            await cache.delete(obj.meta)
            return
        k8s_object = obj.to_k8s_object()
        k8s_object.user_id = obj.user_id
        await cache.upsert(k8s_object)

    return handler
