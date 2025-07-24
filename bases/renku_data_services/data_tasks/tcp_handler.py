"""Handling the tcp connections."""

import re
from asyncio.streams import StreamReader, StreamWriter

from renku_data_services.data_tasks.taskman import TaskManager


class TcpHandler:
    """Handles the simple tcp connection."""

    def __init__(self, tm: TaskManager) -> None:
        self.__task_manager = tm

    async def _write_line(self, writer: StreamWriter, line: str) -> None:
        try:
            writer.write(str.encode(f"{line}\r\n"))
            await writer.drain()
        except Exception:
            pass  # nosec B110

    async def _read_line(self, reader: StreamReader) -> tuple[str, list[str]]:
        try:
            data = await reader.read(100)
            msg = data.decode().strip()
            parts = re.split("\\s+", msg)
            return (parts[0].lower(), parts[1:])
        except Exception:
            return ("", [])

    async def run(self, reader: StreamReader, writer: StreamWriter) -> None:
        """Handles a tcp connection."""
        await self._write_line(writer, "Hello, write `help` for help.")

        while True:
            (cmd, rest) = await self._read_line(reader)
            match cmd:
                case "help":
                    await self._write_line(
                        writer,
                        (
                            "Commands\r\n"
                            "- help: this help text\r\n"
                            "- tasks: list tasks\r\n"
                            "- reset_restarts [name]: reset the restarts counter"
                        ),
                    )

                case "tasks":
                    for t in self.__task_manager.current_tasks():
                        await self._write_line(writer, f"- {t.name}: since {t.started} ({t.restarts} restarts)")

                case "reset_restarts":
                    if rest != []:
                        self.__task_manager.reset_restarts(rest[0])
                    else:
                        for t in self.__task_manager.current_tasks():
                            self.__task_manager.reset_restarts(t.name)
                    await self._write_line(writer, "Ok")

                case _:
                    await self._write_line(writer, "Good Bye.")
                    break
