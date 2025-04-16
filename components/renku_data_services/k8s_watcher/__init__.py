"""K8s watcher and k8s clients."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from asyncio import CancelledError, Task
from datetime import timedelta

from renku_data_services.k8s.models import ClusterId
from renku_data_services.k8s_watcher.db import APIObjectInCluster, Cluster, EventHandler


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
                async for _, obj in watch:
                    await self.__handler(APIObjectInCluster(obj, cluster.id))
                    # in some cases, the kr8s loop above just never yields, especially if there's exceptions which
                    # can bypass async scheduling. This sleep here is as a last line of defence so this code does not
                    # execute indefinitely and prevent an other resource kind from being watched.
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
