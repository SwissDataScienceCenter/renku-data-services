"""The task definitions in form of coroutines."""

import asyncio
import logging

import renku_data_services.search.core as search_core
from renku_data_services.data_tasks.config import Config
from renku_data_services.data_tasks.taskman import TaskDefininions
from renku_data_services.message_queue.db import EventRepository
from renku_data_services.message_queue.redis_queue import RedisQueue
from renku_data_services.metrics.db import MetricsRepository
from renku_data_services.search.db import SearchUpdatesRepo
from renku_data_services.solr.solr_client import DefaultSolrClient

logger = logging.getLogger(__name__)


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


async def send_metrics_to_posthog(cfg: Config) -> None:
    """Send pending product metrics to posthog."""
    from posthog import Posthog

    posthog = Posthog(
        api_key=cfg.posthog_config.api_key,
        host=cfg.posthog_config.host,
        sync_mode=True,
        super_properties={"environment": cfg.posthog_config.environment},
    )
    repo = MetricsRepository(cfg.db_config.async_session_maker)

    while True:
        try:
            metrics = repo.get_unprocessed_metrics()

            processed_ids = []
            async for metric in metrics:
                try:
                    posthog.capture(
                        distinct_id=metric.anonymous_user_id,
                        timestamp=metric.timestamp,
                        event=metric.event,
                        properties=metric.metadata_ or {},
                        # This is sent to avoid duplicate events if multiple instances of data service are running.
                        # Posthog deduplicates events with the same timestamp, distinct_id, event, and uuid fields:
                        # https://github.com/PostHog/posthog/issues/17211#issuecomment-1723136534
                        uuid=metric.id.to_uuid4(),
                    )
                except Exception as e:
                    logger.error(f"Failed to process metrics event {metric.id}: {e}")
                else:
                    processed_ids.append(metric.id)

            await repo.delete_processed_metrics(processed_ids)
        except (asyncio.CancelledError, KeyboardInterrupt) as e:
            logger.warning(f"Exiting: {e}")
            return
        else:
            # NOTE: Sleep 10 seconds between processing cycles
            await asyncio.sleep(10)


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
            "send_product_metrics": lambda: send_metrics_to_posthog(cfg),
        }
    )
