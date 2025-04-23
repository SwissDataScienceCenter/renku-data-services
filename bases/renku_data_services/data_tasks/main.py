"""The entrypoint for the data service application."""

import asyncio
import logging
from asyncio.streams import StreamReader, StreamWriter

from renku_data_services.data_tasks.config import Config
from renku_data_services.data_tasks.task_defs import all_tasks
from renku_data_services.data_tasks.taskman import TaskDefininion, TaskManager


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


class TcpHandler:
    """Handles the simple tcp connection."""

    def __init__(self, tm: TaskManager) -> None:
        self.__task_manager = tm

    async def run(self, reader: StreamReader, writer: StreamWriter) -> None:
        """Handles a tcp connection."""
        writer.write(b"Hello, write `info` for task list, other to quit\r\n")
        await writer.drain()
        while True:
            data = await reader.read(100)
            try:
                message = data.decode().strip().lower()
            except Exception:
                message = ""
            match message:
                case "info":
                    for t in self.__task_manager.current_tasks():
                        writer.write(str.encode(f"- {t.name}: since {t.started} ({t.restarts} restarts)\r\n"))
                        await writer.drain()

                case _:
                    try:
                        writer.write(b"good bye\r\n")
                        await writer.drain()
                        writer.close()
                        await writer.wait_closed()
                    except Exception:
                        pass  # nosec B110
                    break


async def main() -> None:
    """Data tasks entry point."""
    config = Config.from_env()
    configure_logging()
    logger = logging.getLogger("renku_data_services.data_tasks.main")

    tm = TaskManager(config.max_retry_wait)
    internal_tasks = TaskDefininion({"_log_tasks": lambda: log_tasks(logger, tm, config.main_tick_interval)})
    logger.info("Tasks starting...")
    tm.start_all(all_tasks(config).merge(internal_tasks))

    logger.info(f"Starting tcp server at {config.tcp_host}:{config.tcp_port}")
    tcp_handler = TcpHandler(tm)
    server = await asyncio.start_server(tcp_handler.run, config.tcp_host, config.tcp_port)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
    print("Main ended")
