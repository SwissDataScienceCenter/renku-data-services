"""A simple task manager."""

from __future__ import annotations

import asyncio
import logging
from asyncio.tasks import Task
from collections.abc import Callable, Coroutine, Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, final

logger = logging.getLogger(__name__)

type TaskFactory = Callable[[], Coroutine[Any, Any, None]]


@final
class TaskDefininion:
    """Task definitions."""

    def __init__(self, defs: dict[str, TaskFactory]) -> None:
        self.__task_defs: dict[str, TaskFactory] = defs

    @property
    def tasks(self) -> Iterator[tuple[str, TaskFactory]]:
        """Return the set of tasks."""
        return iter(self.__task_defs.items())

    def merge(self, other: TaskDefininion) -> TaskDefininion:
        """Create a new definition merging this with other."""
        return TaskDefininion(self.__task_defs | other.__task_defs)


@final
@dataclass
class TaskContext:
    """Information about a running task."""

    name: str
    task: Task[None]
    started: datetime
    restarts: int

    def inc_restarts(self) -> None:
        """Increments the restart counter."""
        self.restarts = self.restarts + 1

    @property
    def running_time(self) -> timedelta:
        """Return the time the task is running."""
        return datetime.now() - self.started


@final
class TaskManager:
    """State containing currently running tasks associated by their name."""

    def __init__(self, max_retry_wait: int) -> None:
        self.__running_tasks: dict[str, TaskContext] = {}
        self.__max_retry_wait = max_retry_wait

    def start_all(self, task_defs: TaskDefininion) -> None:
        """Registers all tasks."""
        now = datetime.now()
        for name, tf in task_defs.tasks:
            self.start(name, tf, now)

    def start(self, name: str, tf: TaskFactory, now: datetime = datetime.now()) -> None:
        """Start a task associated to the given name."""
        if name in self.__running_tasks:
            logger.warning(f"{name}: not starting task, it is already running.")
        else:
            self.__start(name, tf, now)

    def __start(self, name: str, tf: TaskFactory, now: datetime) -> None:
        wt = self.__wrap_task(name, tf)
        logger.info(f"{name}: Starting...")
        t = asyncio.create_task(wt, name=name)
        ctx = TaskContext(name=name, task=t, started=now, restarts=0)
        self.__running_tasks.update({name: ctx})
        t.add_done_callback(lambda tt: self.__remove_running(tt.get_name()))

    def cancel(self, name: str) -> bool:
        """Cancel the task with the given name.

        Return true if the task is currently running and requested to
        cancel, false if there is no task with the given name.
        """
        t = self.__running_tasks.get(name)
        if t is None:
            return False
        else:
            logger.info(f"{t.name}: cancelling task")
            t.task.cancel()
            return True

    def __remove_running(self, name: str) -> None:
        v = self.__running_tasks.pop(name, None)
        if v is None:
            logger.warning(f"Task {name} was expected in running state, but is not found.")
        else:
            logger.debug(f"{name}: removed from running set")

    async def __wrap_task(self, name: str, tf: TaskFactory) -> None:
        while True:
            try:
                await tf()
                ctx = self.__running_tasks.get(name)
                if ctx is not None:
                    logger.info(f"{name}: Finished in {ctx.running_time.seconds}s")
                break
            except Exception as e:
                ctx = self.__running_tasks.get(name)
                restarts = 0
                if ctx is not None:
                    restarts = ctx.restarts
                    ctx.inc_restarts()

                secs = min(pow(2, restarts), self.__max_retry_wait)
                logger.error(
                    f"{name}: Failed with {e}. Restarting it in {secs} seconds for the {restarts + 1}. time.",
                    exc_info=e,
                )
                await asyncio.sleep(secs)
