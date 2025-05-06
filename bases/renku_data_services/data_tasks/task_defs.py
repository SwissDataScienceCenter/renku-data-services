"""The task definitions in form of coroutines."""

import asyncio

import renku_data_services.search.core as search_core
from renku_data_services.data_tasks.config import Config
from renku_data_services.data_tasks.taskman import TaskDefininions
from renku_data_services.message_queue.db import EventRepository
from renku_data_services.message_queue.redis_queue import RedisQueue
from renku_data_services.search.db import SearchUpdatesRepo
from renku_data_services.solr.solr_client import DefaultSolrClient


async def update_search(cfg: Config) -> None:
    """Update the SOLR with data from the search staging table."""
    repo = SearchUpdatesRepo(cfg.db_config.async_session_maker)
    while True:
        async with DefaultSolrClient(cfg.solr_config) as client:
            await search_core.update_solr(repo, client, 20)
        await asyncio.sleep(1)


async def send_pending_redis_events(cfg: Config) -> None:
    """Send pending messages to redis."""
    repo = EventRepository(cfg.db_config.async_session_maker, RedisQueue(cfg.redis_config))
    while True:
        await repo.send_pending_events()
        await asyncio.sleep(1)


def all_tasks(cfg: Config) -> TaskDefininions:
    """A dict of task factories to be managed in main."""
    # Impl. note: We pass the entire config to the coroutines, because
    # should such a task fail it will be restarted, which means the
    # coroutine is re-created. In this case it might be better to also
    # re-create its entire state. If we pass already created
    # repositories or other services (and they are not stateless) we
    # might capture this state and possibly won't recover by
    # re-entering the coroutine.
    return TaskDefininions(
        {
            "update_search": lambda: update_search(cfg),
            "send_pending_events": lambda: send_pending_redis_events(cfg),
        }
    )
