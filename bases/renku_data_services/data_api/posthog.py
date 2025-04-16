"""Sanic task for processing metrics data and sending to PostHog."""

import asyncio

import uvloop
from sanic.log import logger

from renku_data_services.app_config import Config


async def _send_metrics_to_posthog() -> None:
    from posthog import Posthog

    config = Config.from_env()

    posthog = Posthog(
        api_key=config.posthog.api_key,
        host=config.posthog.host,
        sync_mode=True,
        super_properties={"environment": config.posthog.environment},
    )

    while True:
        try:
            metrics = config.metrics_repo.get_unprocessed_metrics()

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

            await config.metrics_repo.delete_processed_metrics(processed_ids)
        except (asyncio.CancelledError, KeyboardInterrupt) as e:
            logger.warning(f"Exiting: {e}")
            return
        else:
            # NOTE: Sleep 10 seconds between processing cycles
            await asyncio.sleep(10)


def start_metrics_task() -> None:
    """Start the metrics processing task."""
    asyncio.set_event_loop(uvloop.new_event_loop())
    asyncio.run(_send_metrics_to_posthog())
