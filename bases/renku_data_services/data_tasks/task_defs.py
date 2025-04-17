"""The task definitions in form of coroutines."""

import asyncio

from renku_data_services.data_tasks.config import Config
from renku_data_services.data_tasks.taskman import TaskDefininion


async def finite_but_long_task(secs: int) -> None:
    """Bla."""
    print("Hello....")
    await asyncio.sleep(secs)
    print("World!!! and done")


async def endless_task1(name: str, max: int) -> None:
    """Just testing."""
    counter = 0
    while True:
        print(f"{name} counter: {counter}")
        if counter >= max:
            raise Exception(f"{name} booom!")
        await asyncio.sleep(1)
        counter += 1


def all_tasks(cfg: Config) -> TaskDefininion:
    """A dict of task factories to be managed in main."""
    return TaskDefininion(
        {
            "my_long_task": lambda: finite_but_long_task(4),
            "endless one": lambda: endless_task1("one", 8),
            "endless two": lambda: endless_task1("two", 5),
        }
    )
