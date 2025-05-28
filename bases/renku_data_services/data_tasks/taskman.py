"""A simple task manager."""

from __future__ import annotations

import asyncio
import math
import sys
from asyncio.tasks import Task
from collections.abc import Callable, Coroutine, Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, final

from renku_data_services.app_config import logging

logger = logging.getLogger(__name__)

type TaskFactory = Callable[[], Coroutine[Any, Any, None]]
"""A function creating a coroutine."""


@final
class TaskDefininions:
    """Task definitions."""

    def __init__(self, defs: dict[str, TaskFactory]) -> None:
        self.__task_defs = defs

    @classmethod
    def single(cls, name: str, tf: TaskFactory) -> TaskDefininions:
        """Create a TaskDefinition for the given single task."""
        return TaskDefininions({name: tf})

    @property
    def tasks(self) -> Iterator[tuple[str, TaskFactory]]:
        """Return the set of tasks."""
        return iter(self.__task_defs.items())

    def merge(self, other: TaskDefininions) -> TaskDefininions:
        """Create a new definition merging this with other."""
        return TaskDefininions(self.__task_defs | other.__task_defs)


@final
@dataclass(frozen=True)
class TaskView:
    """Information about a running task."""

    name: str
    started: datetime
    restarts: int


@final
@dataclass
class _TaskContext:
    """Information (internal) about a running task."""

    name: str
    task: Task[None]
    started: datetime
    restarts: int

    def inc_restarts(self) -> None:
        """Increments the restart counter."""
        self.restarts = self.restarts + 1

    def reset_restarts(self) -> None:
        """Resets the restarts counter to 0."""
        self.restarts = 0

    def running_time(self, ref: datetime = datetime.now()) -> timedelta:
        """Return the time the task is running."""
        return ref - self.started

    def to_view(self) -> TaskView:
        """Convert this into a view object."""
        return TaskView(self.name, self.started, self.restarts)


@final
class TaskJoin:
    """Used to wait for a task to finish."""

    def __init__(self, tm: TaskManager, name: str) -> None:
        self.__task_manager = tm
        self.__task_name = name

    def get_view(self) -> TaskView | None:
        """Return the current task view."""
        return self.__task_manager.get_task_view(self.__task_name)

    async def join(self, max_wait: float) -> None:
        """Wait for this task to finish execution."""
        tv = self.get_view()
        counter: int = 0
        max_count: int = sys.maxsize if max_wait <= 0 else math.ceil(max_wait / 0.1)
        while tv is not None:
            await asyncio.sleep(0.1)
            tv = self.get_view()
            counter += 1
            if counter >= max_count:
                raise TimeoutError(f"Task is still running, after {max_wait}s")


@final
class TaskManager:
    """Maintains state for currently running tasks associated by their name."""

    def __init__(self, max_retry_wait_seconds: int) -> None:
        self.__running_tasks: dict[str, _TaskContext] = {}
        self.__max_retry_wait_seconds = max_retry_wait_seconds

    def start_all(self, task_defs: TaskDefininions, start_time: datetime = datetime.now()) -> None:
        """Registers all tasks."""
        now = start_time
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
        ctx = _TaskContext(name=name, task=t, started=now, restarts=0)
        self.__running_tasks.update({name: ctx})
        t.add_done_callback(lambda tt: self.__remove_running(tt.get_name()))

    def current_tasks(self) -> list[TaskView]:
        """Return a list of currently running tasks."""
        return [e.to_view() for e in self.__running_tasks.values()]

    def get_task_view(self, name: str) -> TaskView | None:
        """Return information about a currently running task."""
        t = self.__running_tasks.get(name)
        if t is not None:
            return t.to_view()
        else:
            return None

    def get_task_join(self, name: str) -> TaskJoin:
        """Returns a TaskJoin object for the given task."""
        return TaskJoin(self, name)

    def reset_restarts(self, name: str) -> None:
        """Resets the restarts counter to 0."""
        tc = self.__running_tasks.get(name)
        if tc is not None:
            tc.reset_restarts()

    def cancel(self, name: str) -> TaskJoin | None:
        """Cancel the task with the given name.

        Return a `TaskJoin` object if the task is currently running
        and requested to cancel, `None` if there is no task with the
        given name.
        """
        t = self.__running_tasks.get(name)
        if t is None:
            return None
        else:
            logger.info(f"{t.name}: cancelling task")
            t.task.cancel()
            return self.get_task_join(name)

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
                    logger.info(f"{name}: Finished in {ctx.running_time().seconds}s")
                break
            except Exception as e:
                ctx = self.__running_tasks.get(name)
                restarts = 0
                if ctx is not None:
                    restarts = ctx.restarts
                    ctx.inc_restarts()

                secs = min(pow(2, restarts), self.__max_retry_wait_seconds)
                logger.error(
                    f"{name}: Failed with {e}. Restarting it in {secs} seconds for the {restarts + 1}. time.",
                    exc_info=e,
                )
                await asyncio.sleep(secs)
