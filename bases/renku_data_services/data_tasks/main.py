"""The entrypoint for the data service application."""

import asyncio
import logging

import uvloop

from renku_data_services.data_tasks.config import Config
from renku_data_services.data_tasks.task_defs import all_tasks
from renku_data_services.data_tasks.taskman import TaskDefininions, TaskManager
from renku_data_services.data_tasks.tcp_handler import TcpHandler


def configure_logging() -> None:
    """Configures logging.

    Log everything at level WARNING, except for our code that is set to INFO
    """
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    logging.getLogger("renku_data_services").setLevel(logging.INFO)


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
    config = Config.from_env()
    configure_logging()
    logger = logging.getLogger("renku_data_services.data_tasks.main")
    logger.info(f"Config: {config}")

    tm = TaskManager(config.max_retry_wait_seconds)
    internal_tasks = TaskDefininions({"_log_tasks": lambda: log_tasks(logger, tm, config.main_log_interval_seconds)})
    logger.info("Tasks starting...")
    tm.start_all(all_tasks(config).merge(internal_tasks))

    logger.info(f"Starting tcp server at {config.tcp_host}:{config.tcp_port}")
    tcp_handler = TcpHandler(tm)
    server = await asyncio.start_server(tcp_handler.run, config.tcp_host, config.tcp_port)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    uvloop.run(main())
