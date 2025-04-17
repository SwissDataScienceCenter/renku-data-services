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
    logger = logging.getLogger(__name__)

    tm = TaskManager(config.max_retry_wait)
    logger.info("Tasks starting...")
    tm.start_all(all_tasks(config))

    while True:
        await asyncio.sleep(300)


if __name__ == "__main__":
    asyncio.run(main())


## TODO or some ideas
##
## - tests…
## - add a sanic handler to be able to do some basic controlling:
##   - cancellation, manual restarts
##   - getting list of currently running tasks
##   - trigger a coordinated shutdown
## - log every tick interval (300s) the current state
## - configure more stuff and implement from_env
## - implement real task, like event sending or search updates
