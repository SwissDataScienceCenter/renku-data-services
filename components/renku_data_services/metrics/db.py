"""Repository for the metrics staging table."""

import asyncio
from collections.abc import AsyncGenerator, Callable
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from renku_data_services.metrics.orm import MetricsORM


class MetricsRepository:
    """Repository for the metrics staging table."""

    def __init__(self, session_maker: Callable[..., AsyncSession]) -> None:
        """Initialize a new metrics repository."""
        self.session_maker = session_maker

    async def store_event(self, event: str, anonymous_user_id: str, metadata: dict[str, Any] | None) -> None:
        """Store a metrics event in the staging table."""
        metric_orm = MetricsORM(event=event, anonymous_user_id=anonymous_user_id, metadata_=metadata)

        async with self.session_maker() as session, session.begin():
            session.add(metric_orm)

    async def get_unprocessed_metrics(self) -> AsyncGenerator[MetricsORM, None]:
        """Get unprocessed metrics events from the staging table."""
        async with self.session_maker() as session:
            result = await session.stream_scalars(select(MetricsORM))
            async for metrics in result:
                yield metrics

    async def delete_all_metrics(self) -> None:
        """Delete all metrics from the staging table."""
        async with self.session_maker() as session, session.begin():
            await session.execute(delete(MetricsORM))

    async def delete_processed_metrics(self, metrics_ids: list[ULID]) -> None:
        """Delete metrics events from the staging table."""
        if not metrics_ids:
            return
        async with self.session_maker() as session, session.begin():
            await session.execute(delete(MetricsORM).where(MetricsORM.id.in_(metrics_ids)))

    async def wait_for_metrics(self, timeout: float = 5.0, poll_interval: float = 0.1) -> bool:
        """Wait for metrics to be processed.

        Polls for metrics events and returns when at least one event is found or timeout is reached.

        Args:
            timeout: Maximum time to wait in seconds
            poll_interval: Time between polls in seconds

        Returns:
            True if metrics were found, False if timeout reached
        """
        import time

        start_time = time.monotonic()
        while time.monotonic() - start_time < timeout:
            metrics = [m async for m in self.get_unprocessed_metrics()]
            if metrics:
                return True
            await asyncio.sleep(poll_interval)
        return False
