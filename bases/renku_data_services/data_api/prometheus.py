"""Prometheus Metrics."""

import asyncio
import resource

import aiofiles
from prometheus_client import Gauge
from prometheus_sanic import monitor
from prometheus_sanic.constants import BaseMetrics
from prometheus_sanic.metrics import init
from sanic import Sanic

_PAGESIZE = resource.getpagesize()
PROMETHEUS_VIRTUAL_MEMORY = "sanic_process_virtual_memory_bytes"
PROMETHEUS_RESIDENT_MEMORY = "sanic_process_resident_memory_bytes"
PROMETHEUS_METRICS_LIST = [
    (
        PROMETHEUS_VIRTUAL_MEMORY,
        Gauge(PROMETHEUS_VIRTUAL_MEMORY, "Virtual memory size in bytes.", ["worker"]),
    ),
    (
        PROMETHEUS_RESIDENT_MEMORY,
        Gauge(PROMETHEUS_RESIDENT_MEMORY, "Resident memory size in bytes.", ["worker"]),
    ),
]


async def collect_system_metrics(app: Sanic, name: str) -> None:
    """Collect prometheus system metrics in a background task.

    This is similar to the official prometheus_client implementation, which doesn't support CPU/Mem metrics
    in multiprocess mode
    """
    try:
        async with aiofiles.open("/proc/self/stat", "rb") as stat:
            content = await stat.read()
            parts = content.split(b")")[-1].split()
        app.ctx.metrics[PROMETHEUS_VIRTUAL_MEMORY].labels({name}).set(float(parts[20]))
        app.ctx.metrics[PROMETHEUS_RESIDENT_MEMORY].labels({name}).set(float(parts[21]) * _PAGESIZE)
    except OSError:
        pass


async def collect_system_metrics_task(app: Sanic) -> None:
    """Background task to collect metrics."""
    while True:
        name = app.name if not hasattr(app.multiplexer) else app.multiplexer.name
        await collect_system_metrics(app, name)
        await asyncio.sleep(5)


def setup_prometheus(app: Sanic) -> None:
    """Setup prometheus monitoring.

    We add custom metrics collection wo sanic workers and to the send_messages background job, since
    prometheus does not collect cpy/memory metrics when in multiprocess mode.
    """
    app.add_task(collect_system_metrics_task)  # type:ignore[arg-type]
    monitor(
        app,
        endpoint_type="url",
        multiprocess_mode="all",
        is_middleware=True,
        metrics_list=PROMETHEUS_METRICS_LIST,
    ).expose_endpoint()


def setup_app_metrics(app: Sanic) -> None:
    """Setup metrics for a Sanic app.

    NOTE: this should only be called for manually created workers (with app.manager.manage(...))
    """
    app.ctx.metrics = {}
    init(app, metrics_list=PROMETHEUS_METRICS_LIST, metrics=BaseMetrics)
