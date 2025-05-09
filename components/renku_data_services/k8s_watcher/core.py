"""K8s watcher main."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from asyncio import CancelledError, Task
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Self, cast

from box import Box
from kr8s._api import Api
from kr8s.asyncio.objects import APIObject

from renku_data_services.base_models.core import APIUser, InternalServiceAdmin, ServiceAdminId
from renku_data_services.base_models.metrics import MetricsService
from renku_data_services.crc.db import ResourcePoolRepository
from renku_data_services.errors import errors
from renku_data_services.k8s.models import Cluster, ClusterId, K8sObject, K8sObjectMeta
from renku_data_services.k8s_watcher.db import K8sDbCache
from renku_data_services.notebooks.crs import State
from renku_data_services.session.constants import DUMMY_TASK_RUN_USER_ID


@dataclass
class APIObjectInCluster:
    """A kr8s k8s object from a specific cluster."""

    obj: APIObject
    cluster: ClusterId

    @property
    def user_id(self) -> str | None:
        """Extract the user id from annotations."""
        match self.obj.singular:
            case "jupyterserver":
                return cast(str, self.obj.metadata.labels["renku.io/userId"])
            case "amaltheasession":
                return cast(str, self.obj.metadata.labels["renku.io/safe-username"])
            case "buildrun":
                return cast(str, self.obj.metadata.labels["renku.io/safe-username"])

            case "taskrun":
                return DUMMY_TASK_RUN_USER_ID
            case _:
                return None

    @property
    def meta(self) -> K8sObjectMeta:
        """Extract the metadata from an api object."""
        return K8sObjectMeta(
            name=self.obj.name,
            namespace=self.obj.namespace or "default",
            cluster=self.cluster,
            version=self.obj.version,
            kind=self.obj.kind,
            user_id=self.user_id,
        )

    def to_k8s_object(self) -> K8sObject:
        """Convert the api object to a regular k8s object."""
        if self.obj.name is None or self.obj.namespace is None:
            raise errors.ProgrammingError()
        return K8sObject(
            name=self.obj.name,
            namespace=self.obj.namespace,
            kind=self.obj.kind,
            version=self.obj.version,
            manifest=Box(self.obj.to_dict()),
            cluster=self.cluster,
            user_id=self.user_id,
        )

    @classmethod
    def from_k8s_object(cls, obj: K8sObject, api: Api) -> Self:
        """Convert a regular k8s object to an api object."""

        return cls(
            obj=obj.to_api_object(api),
            cluster=obj.cluster,
        )


type EventHandler = Callable[[APIObjectInCluster, str], Awaitable[None]]

k8s_watcher_admin_user = InternalServiceAdmin(id=ServiceAdminId.k8s_watcher)


class K8sWatcher:
    """Watch k8s events and call the handler with every event."""

    def __init__(self, handler: EventHandler, clusters: dict[ClusterId, Cluster], kinds: list[str]) -> None:
        self.__handler = handler
        self.__tasks: dict[ClusterId, list[Task]] | None = None
        self.__kinds = kinds
        self.__clusters = clusters

    async def __watch_kind(self, kind: str, cluster: Cluster) -> None:
        while True:
            try:
                watch = cluster.api.async_watch(kind=kind, namespace=cluster.namespace)
                async for event_type, obj in watch:
                    await self.__handler(APIObjectInCluster(obj, cluster.id), event_type)
                    # in some cases, the kr8s loop above just never yields, especially if there's exceptions which
                    # can bypass async scheduling. This sleep here is as a last line of defence so this code does not
                    # execute indefinitely and prevent another resource kind from being watched.
                    await asyncio.sleep(0)
            except Exception as e:
                logging.error(f"watch loop failed for {kind} in cluster {cluster.id}", exc_info=e)
                # without sleeping, this can just hang the code as exceptions seem to bypass the async scheduler
                await asyncio.sleep(1)
                pass

    def __run_single(self, cluster: Cluster) -> list[Task]:
        # The loops and error handling here will need some testing and love
        tasks = []
        for kind in self.__kinds:
            logging.info(f"watching {kind} in cluster {cluster.id}")
            tasks.append(asyncio.create_task(self.__watch_kind(kind, cluster)))

        return tasks

    async def start(self) -> None:
        """Start the watcher."""
        if self.__tasks is None:
            self.__tasks = {}
        for cluster in self.__clusters.values():
            self.__tasks[cluster.id] = self.__run_single(cluster)

    async def wait(self) -> None:
        """Wait for all tasks.

        This is mainly used to block the main function.
        """
        if self.__tasks is None:
            return
        await asyncio.gather(*[t for tl in self.__tasks.values() for t in tl])

    async def stop(self, timeout: timedelta = timedelta(seconds=10)) -> None:
        """Stop the watcher or timeout."""
        if self.__tasks is None:
            return
        for task_list in self.__tasks.values():
            for task in task_list:
                if task.done():
                    continue
                task.cancel()
                try:
                    async with asyncio.timeout(timeout.total_seconds()):
                        with contextlib.suppress(CancelledError):
                            await task
                except TimeoutError:
                    logging.error("timeout trying to cancel k8s watcher task")
                    continue


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
        case State.Hibernated.value if (previous_state != State.Hibernated.value):
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
                logging.error("failed to track product metrics", exc_info=e)
        if event_type == "DELETED":
            await cache.delete(obj.meta)
            return
        k8s_object = obj.to_k8s_object()
        k8s_object.user_id = obj.user_id
        await cache.upsert(k8s_object)

    return handler
