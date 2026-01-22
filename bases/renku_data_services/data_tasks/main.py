"""The entrypoint for the data service application."""

import asyncio

import uvloop

from renku_data_services.app_config import logging
from renku_data_services.data_tasks.dependencies import DependencyManager
from renku_data_services.data_tasks.task_defs import all_tasks
from renku_data_services.data_tasks.taskman import TaskDefininions, TaskManager
from renku_data_services.data_tasks.tcp_handler import TcpHandler

logger = logging.getLogger(__name__)


async def log_tasks(logger: logging.Logger, tm: TaskManager, interval: int) -> None:
    """Log the currently running tasks each `interval`."""
    while interval > 0:
        await asyncio.sleep(interval)
        tasks = tm.current_tasks()
        tasks.sort(key=lambda e: e.name)
        lines = "\n".join([f"- {e.name}: since {e.started} ({e.restarts} restarts)" for e in tasks])
        logger.info(f"********* Tasks ********\n{lines}")


async def main() -> None:
    """Data tasks entry point."""
    dm = DependencyManager.from_env()
    logger.info(f"Config: {dm.config}")

    tm = TaskManager(dm.config.max_retry_wait_seconds)
    internal_tasks = TaskDefininions({"_log_tasks": lambda: log_tasks(logger, tm, dm.config.main_log_interval_seconds)})
    logger.info("Tasks starting...")
    tm.start_all(all_tasks(dm).merge(internal_tasks))

    logger.info(f"Starting tcp server at {dm.config.tcp_host}:{dm.config.tcp_port}")
    tcp_handler = TcpHandler(tm)
    server = await asyncio.start_server(tcp_handler.run, dm.config.tcp_host, dm.config.tcp_port)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    uvloop.run(main())
