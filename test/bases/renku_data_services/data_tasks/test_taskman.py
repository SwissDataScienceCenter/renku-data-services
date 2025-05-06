"""Tests for taskman module."""

import asyncio
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import pytest

from renku_data_services.data_tasks.taskman import TaskDefininions, TaskManager, _TaskContext

logger = logging.getLogger(__name__)


async def task1(wait_time: float, body: Callable[[], Any] = lambda: logger.info("hello world")) -> None:
    await asyncio.sleep(wait_time)
    body()


async def task2(wait_time: float, body: Callable[[], Any] = lambda: logger.info("hello world")) -> None:
    while True:
        body()
        await asyncio.sleep(wait_time)


def test_task_definition() -> None:
    td = TaskDefininions({"test1": lambda: task1(1)})
    tds = list(td.tasks)
    assert len(tds) == 1
    for name, tf in td.tasks:
        assert name == "test1"
        assert isinstance(tf(), Coroutine)


def test_task_context() -> None:
    started = datetime(2025, 4, 21, 15, 30, 0)
    delta = timedelta(seconds=154)
    tc = _TaskContext(name="test1", task=..., started=started, restarts=0)

    assert tc.restarts == 0
    tc.inc_restarts()
    assert tc.restarts == 1

    td = tc.running_time(ref=started + delta)
    assert td == delta


@dataclass
class State:
    counter: int = 0
    throw_on: int = -1

    def set(self, n: int) -> None:
        self.counter = n
        if n == self.throw_on:
            raise Exception(f"Error on {n}")

    def inc(self) -> None:
        self.set(self.counter + 1)


async def cancel(tm: TaskManager, name: str, max_wait: float) -> None:
    tj = tm.cancel(name)
    if tj is not None:
        await tj.join(max_wait)
    else:
        raise Exception(f"Task {name} not found")


@pytest.mark.asyncio
async def test_simple_task_run() -> None:
    tm = TaskManager(max_retry_wait_seconds=10)
    state = State()
    td = TaskDefininions.single("task1", lambda: task1(0.5, state.inc))
    tm.start_all(td)
    assert tm.get_task_view("task1") is not None
    await tm.get_task_join("task1").join(max_wait=1)
    assert tm.get_task_view("task1") is None
    assert state.counter == 1


@pytest.mark.asyncio
async def test_infinite_task() -> None:
    tm = TaskManager(max_retry_wait_seconds=10)
    state = State()
    td = TaskDefininions.single("task", lambda: task2(0.1, state.inc))
    tm.start_all(td)
    assert tm.get_task_view("task") is not None
    await asyncio.sleep(0.5)
    assert tm.get_task_view("task") is not None
    assert state.counter > 3
    await cancel(tm, "task", 1)


@pytest.mark.asyncio
async def test_retry_on_error() -> None:
    tm = TaskManager(max_retry_wait_seconds=1)
    state = State(throw_on=2)
    td = TaskDefininions.single("task", lambda: task2(0.1, state.inc))
    tm.start_all(td)
    await asyncio.sleep(2)
    assert tm.get_task_view("task") is not None
    assert state.counter > 2
    tv = tm.get_task_view("task")
    assert tv is not None
    assert tv.restarts > 0
    await cancel(tm, "task", 1)


@pytest.mark.asyncio
async def test_task_cancel() -> None:
    tm = TaskManager(max_retry_wait_seconds=1)
    state = State()
    td = TaskDefininions.single("task", lambda: task2(0.1, state.inc))
    tm.start_all(td)
    await asyncio.sleep(0.5)
    assert tm.get_task_view("task") is not None
    assert tm.cancel("task") is not None
    assert tm.cancel("bla") is None
    await tm.get_task_join("task").join(1)
    assert tm.get_task_view("task") is None
