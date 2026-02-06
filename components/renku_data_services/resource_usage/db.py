"""Repository implementation."""

from collections.abc import AsyncGenerator, AsyncIterator, Callable, Generator, Iterable, Sequence
from datetime import datetime
from itertools import islice

import sqlalchemy.sql as sa
from sqlalchemy import bindparam
from sqlalchemy.ext.asyncio import AsyncSession

from renku_data_services.app_config import logging
from renku_data_services.resource_usage.model import (
    ResourceClassCostQuery,
    ResourcePoolLimits,
    ResourcesRequest,
    ResourceUsage,
    ResourceUsageQuery,
)
from renku_data_services.resource_usage.orm import (
    ResourceClassCost,
    ResourceClassCostORM,
    ResourceRequestsLimitsORM,
    ResourceRequestsLogORM,
    ResourceRequestsViewORM,
)
from renku_data_services.utils.sqlalchemy import CreditType

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

    async def set_resource_class_costs(self, costs: ResourceClassCost) -> None:
        """Updates (inserts or update) the costs of a resource_class."""
        stmt = sa.text("""
        insert into resource_pools.resource_class_costs (resource_class_id, cost_hours)
        values (:resource_class_id, :cost_hours)
        on conflict (resource_class_id) do update
        set
          cost_hours = EXCLUDED.cost_hours
        """)
        async with self.session_maker() as session, session.begin():
            await session.execute(stmt, costs.__dict__)

    async def delete_resource_class_costs(self, resource_class_id: int) -> None:
        """Remove a cost associated to a resource_class."""
        stmt = sa.text("delete from resource_pools.resource_class_costs where resource_class_id = :id")
        async with self.session_maker() as session, session.begin():
            await session.execute(stmt, {"id": resource_class_id})

    async def find_resource_class_costs(self, resource_class_id: int) -> ResourceClassCost | None:
        """Finds the costs of  the given resource class."""
        stmt = sa.select(ResourceClassCostORM).where(ResourceClassCostORM.id == resource_class_id)
        async with self.session_maker() as session:
            result = await session.execute(stmt)
            data = result.scalar_one_or_none()
            return data.dump() if data is not None else None

    async def set_resource_pool_limits(self, limits: ResourcePoolLimits) -> None:
        """Updates (insert or update) the limits of the given pool."""
        stmt = sa.text("""
        insert into resource_pools.resource_requests_limits
          (resource_pool_id, total_limit, user_limit)
        values
          (:pool_id, :total_limit, :user_limit)
        on conflict (resource_pool_id) do update
        set
          total_limit = EXCLUDED.total_limit,
          user_limit = EXCLUDED.user_limit
        """).bindparams(bindparam("total_limit", type_=CreditType()), bindparam("user_limit", type_=CreditType()))
        async with self.session_maker() as session, session.begin():
            await session.execute(stmt, limits.__dict__)

    async def delete_resource_pool_limits(self, pool: int) -> None:
        """Removes limits from the resource pool."""
        stmt = sa.text("delete from resource_pools.resource_requests_limits where resource_pool_id = :pool")
        async with self.session_maker() as session, session.begin():
            await session.execute(stmt, {"pool": pool})

    async def find_resource_pool_limits(self, pool: int) -> ResourcePoolLimits | None:
        """Finds the limits of the given resource pool."""
        stmt = sa.select(ResourceRequestsLimitsORM).where(ResourceRequestsLimitsORM.id == pool)
        async with self.session_maker() as session:
            result = await session.execute(stmt)
            data = result.scalar_one_or_none()
            return data.dump() if data is not None else None

    async def find_usage(self, rq: ResourceUsageQuery, chunk_size: int = 500) -> AsyncGenerator[ResourceUsage]:
        """Find resource usage."""
        by_user = " and user_id = :user_id " if rq.user_id is not None else ""
        by_rp = " and resource_pool_id = :resource_pool_id " if rq.resource_pool_id is not None else ""
        stmt = f"""
          select
            cluster_id,
            user_id,
            resource_pool_id,
            resource_class_id,
            capture_date::date,
            gpu_slice,
            sum(cpu_request * (extract(epoch from cpu_time) / 3600)) as cpu_hours,
            sum(memory_request * (extract(epoch from mem_time) / 3600)) as mem_hours,
            sum(disk_request * (extract(epoch from disk_time) / 3600)) as disk_hours,
            sum(gpu_request * (extract(epoch from gpu_time) / 3600)) as gpu_hours
          from "resource_pools"."resource_requests_view"
          where capture_date::date >= :from and capture_date::date <= :until
              {by_user} {by_rp}
          group by cluster_id, resource_class_id, resource_pool_id, user_id, capture_date::date, gpu_slice
        """
        params = {"from": rq.since, "until": rq.until, "user_id": rq.user_id, "resource_pool_id": rq.resource_pool_id}

        async with self.session_maker() as session:
            query = sa.text(stmt).execution_options(yield_per=chunk_size)
            result = await session.stream(query, params)

            async for row in result:
                ru = ResourceUsage(**row._mapping)
                yield ru

    async def get_resource_class_usage(self, rq: ResourceClassCostQuery) -> ResourceClassCost:
        """Query the current usage of a resource class."""

        by_user = " and user_id = :user_id " if rq.user_id is not None else ""
        stmt = f"""
        select  sum(greatest(cpu_time, mem_time, gpu_time, '0 second'::interval)) as runtime
        from resource_requests_view
        where phase = 'Running'
          and capture_date::date >= :from and capture_date::date <= :until
          and resource_class_id = :class_id {by_user}
        """
        params = {"from": rq.since, "until": rq.until, "user_id": rq.user_id, "class_id": rq.resource_class_id}

        async with self.session_maker() as session:
            query = sa.text(stmt)
            result = await session.execute(query, params)
            row = result.one_or_none()
            return (
                ResourceClassCost(**row._mapping) if row is not None else ResourceClassCost.zero(rq.resource_class_id)
            )
