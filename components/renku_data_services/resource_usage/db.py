"""Repository implementation."""

from collections.abc import AsyncIterator, Callable, Generator, Iterable, Sequence
from itertools import islice

import sqlalchemy.sql as sa
from sqlalchemy.ext.asyncio import AsyncSession

from renku_data_services.app_config import logging
from renku_data_services.resource_usage.model import (
    ResourcesRequest,
)
from renku_data_services.resource_usage.orm import ResourceRequestsLogORM

logger = logging.getLogger(__file__)


class ResourceRequestsRepo:
    """Repository for resource requests data."""

    def __init__(self, session_maker: Callable[..., AsyncSession]) -> None:
        self.session_maker = session_maker

    async def find_all(self, chunk_size: int = 100) -> AsyncIterator[ResourceRequestsLogORM]:
        """Select all records."""
        stmt = sa.select(ResourceRequestsLogORM).order_by(ResourceRequestsLogORM.capture_date.desc())
        async with self.session_maker() as session:
            result = await session.stream(stmt.execution_options(yield_per=chunk_size))
            async for e in result.scalars():
                yield e

    async def insertOne(self, req: ResourcesRequest) -> None:
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
