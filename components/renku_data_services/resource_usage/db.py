"""Repository implementation."""

from collections.abc import AsyncGenerator, AsyncIterator, Callable, Generator, Iterable, Sequence
from datetime import date, datetime
from itertools import islice

import sqlalchemy.sql as sa
from sqlalchemy.ext.asyncio import AsyncSession

from renku_data_services.app_config import logging
from renku_data_services.resource_usage.model import ResourcesRequest, ResourceUsage
from renku_data_services.resource_usage.orm import ResourceRequestsLogORM, ResourceRequestsViewORM

logger = logging.getLogger(__file__)


class ResourceRequestsRepo:
    """Repository for resource requests data."""

    def __init__(self, session_maker: Callable[..., AsyncSession]) -> None:
        self.session_maker = session_maker

    async def find_all(self, chunk_size: int = 100) -> AsyncIterator[ResourceRequestsLogORM]:
        """Select all log records."""
        stmt = sa.select(ResourceRequestsLogORM).order_by(ResourceRequestsLogORM.capture_date.desc())
        async with self.session_maker() as session:
            result = await session.stream(stmt.execution_options(yield_per=chunk_size))
            async for e in result.scalars():
                yield e

    async def insert_one(self, req: ResourcesRequest) -> None:
        """Insert one data into the log."""
        async with self.session_maker() as session, session.begin():
            obj = ResourceRequestsLogORM.from_resources_request(req)
            session.add(obj)
            await session.flush()

    def _chunk_seq[A](self, seq: Iterable[A], size: int = 100) -> Generator[Sequence[A]]:
        it = iter(seq)
        while True:
            chunk = list(islice(it, size))
            if not chunk:
                break
            yield chunk

    async def insert_many(self, reqs: Iterable[ResourcesRequest]) -> None:
        """Insert many values."""
        for chunk in self._chunk_seq(reqs, 100):
            if len(chunk) > 0:
                async with self.session_maker() as session, session.begin():
                    vals = [ResourceRequestsLogORM.from_resources_request(e) for e in chunk]
                    session.add_all(vals)
                    await session.flush()

    async def find_view(
        self, start: datetime, end: datetime, chunk_size: int = 100
    ) -> AsyncIterator[ResourceRequestsViewORM]:
        """Select view records."""
        stmt = (
            sa.select(ResourceRequestsViewORM)
            .where(ResourceRequestsViewORM.capture_date >= start)
            .where(ResourceRequestsViewORM.capture_date <= end)
            .order_by(ResourceRequestsViewORM.capture_date.desc())
        )
        async with self.session_maker() as session:
            result = await session.stream(stmt.execution_options(yield_per=chunk_size))
            async for e in result.scalars():
                yield e

    async def find_usage(self, start: date, end: date, chunk_size: int = 500) -> AsyncGenerator[ResourceUsage]:
        """Find resource usage."""
        stmt = """
          select
            cluster_id,
            user_id,
            resource_pool_id,
            resource_class_id,
            capture_date::date,
            sum(cpu_request * (extract(epoch from cpu_time) / 3600)) as cpu_hours,
            sum(memory_request * (extract(epoch from mem_time) / 3600)) as mem_hours,
            sum(disk_request * (extract(epoch from disk_time) / 3600)) as disk_hours,
            sum(gpu_request * (extract(epoch from gpu_time) / 3600)) as gpu_hours
          from "common"."resource_requests_view"
          where capture_date::date >= :from and capture_date::date <= :until
          group by cluster_id, resource_class_id, resource_pool_id, user_id, capture_date::date
        """

        params = {"from": start, "until": end}

        async with self.session_maker() as session:
            query = sa.text(stmt).execution_options(yield_per=chunk_size)
            result = await session.stream(query, params)

            async for row in result:
                ru = ResourceUsage(**row._mapping)
                yield ru
