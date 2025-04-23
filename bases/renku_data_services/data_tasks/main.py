"""The entrypoint for the data service application."""

import asyncio
import logging

from renku_data_services.data_tasks.config import Config
from renku_data_services.data_tasks.task_defs import all_tasks
from renku_data_services.data_tasks.taskman import TaskManager


def configure_logging() -> None:
    """Configures logging.

    Log everything at level WARNING, except for our code that is set to INFO
    """
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    logging.getLogger("renku_data_services").setLevel(logging.INFO)


async def main() -> None:
    """Data tasks entry point."""
    config = Config.from_env()
    configure_logging()
    logger = logging.getLogger("renku_data_services.data_tasks.main")

    tm = TaskManager(config.max_retry_wait)
    logger.info("Tasks starting...")
    tm.start_all(all_tasks(config))

    while True:
        await asyncio.sleep(config.main_tick_interval)
        tasks = tm.current_tasks()
        tasks.sort(key=lambda e: e.name)
        lines = "\n".join([f"- {e.name}: since {e.started} ({e.restarts} restarts)" for e in tasks])
        logger.info(f"********* Tasks ********\n{lines}")


if __name__ == "__main__":
    asyncio.run(main())
    print("Main ended")
