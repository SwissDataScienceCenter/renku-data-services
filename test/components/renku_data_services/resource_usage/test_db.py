"""Tests for resource data."""

from datetime import UTC, date, datetime, timedelta

import pytest
import sqlalchemy as sa

from renku_data_services.data_api.dependencies import DependencyManager
from renku_data_services.migrations.core import run_migrations_for_app
from renku_data_services.resource_usage.db import ResourceRequestsRepo
from renku_data_services.resource_usage.model import (
    ComputeCapacity,
    Credit,
    DataSize,
    ResourceClassCost,
    ResourceClassCostQuery,
    ResourceUsageQuery,
)
from renku_data_services.resource_usage.orm import ResourcePoolLimits
from test.components.renku_data_services.resource_usage.helper import assert_view_records, make_resources_request


async def create_resource_class(app_manager_instance: DependencyManager) -> tuple[int, int]:
    """Create a resource pool and class."""
    async with app_manager_instance.config.db.async_session_maker() as session, session.begin():
        stmt = sa.text("""
        insert into resource_pools.resource_pools (name,quota,"default","public")
        values ('test', '1',true,true)
        returning id""")
        res = await session.execute(stmt)
        pool_id = res.scalar_one()
        stmt = sa.text("""
        insert into resource_pools.resource_classes
          (name,cpu,gpu,memory,max_storage,default_storage,"default",resource_pool_id)
        values ('test',5,0,1000,1000,500,true,:pool)
        returning id""")
        res = await session.execute(stmt, {"pool": pool_id})
        class_id = res.scalar_one()
        return (pool_id, class_id)


@pytest.mark.asyncio
async def test_resource_class_costs_query(app_manager_instance: DependencyManager) -> None:
    run_migrations_for_app("common")
    repo = ResourceRequestsRepo(app_manager_instance.config.db.async_session_maker)
    first_date = datetime(2026, 1, 24, 23, 55, 4, 0, tzinfo=UTC)
    (_, class_id) = await create_resource_class(app_manager_instance)
    interval = timedelta(minutes=15)
    costs = ResourceClassCost(resource_class_id=class_id, cost=Credit.from_int(150))
    await repo.set_resource_class_costs(costs)
    await repo.insert_many(
        [
            # a pod is running
            make_resources_request(
                date=first_date + i * interval,
                interval=interval,
                cpu_request=0.2,
                memory_request="512Mi",
                user_id="user-1",
                resource_class_id=class_id,
            )
            for i in range(0, 5)
        ]
        + [
            ## pod is down
            make_resources_request(
                date=first_date + i * interval,
                interval=interval,
                cpu_request=0.5,
                memory_request="256Mi",
                phase="Stopped",
                user_id="user-1",
                resource_class_id=class_id,
            )
            for i in range(3, 7)
        ]
        + [
            # user 2
            make_resources_request(
                date=first_date + i * interval,
                interval=interval,
                cpu_request=0.5,
                memory_request="256Mi",
                user_id="user-2",
                resource_class_id=class_id,
            )
            for i in range(0, 12)
        ]
        + [
            # user1 pod is running
            make_resources_request(
                date=first_date + i * interval,
                interval=interval,
                cpu_request=0.2,
                memory_request="512Mi",
                user_id="user-1",
                resource_class_id=class_id,
            )
            for i in range(18, 21)
        ]
    )

    async for item in repo.find_all(chunk_size=100):
        assert item.resource_class_cost == costs.cost

    query_all = ResourceClassCostQuery(
        since=date(2026, 1, 24), until=date(2026, 1, 25), resource_class_id=class_id, user_id=None
    )
    results = await repo.get_resource_class_usage(query_all)
    assert len(results) == 20
    costs = [e.to_effective_costs() for e in results]
    for item in costs:
        assert item == 37.5

    cost_sum = sum(costs)
    assert cost_sum == 750.0

    query_user1 = ResourceClassCostQuery(
        since=date(2026, 1, 24), until=date(2026, 1, 25), resource_class_id=class_id, user_id="user-1"
    )
    results = await repo.get_resource_class_usage(query_user1)
    assert len(results) == 8
    query_user2 = ResourceClassCostQuery(
        since=date(2026, 1, 24), until=date(2026, 1, 25), resource_class_id=class_id, user_id="user-2"
    )
    results = await repo.get_resource_class_usage(query_user2)
    assert len(results) == 12


@pytest.mark.asyncio
async def test_resource_class_costs(app_manager_instance: DependencyManager) -> None:
    run_migrations_for_app("common")
    repo = ResourceRequestsRepo(app_manager_instance.config.db.async_session_maker)
    (pool_id, class_id) = await create_resource_class(app_manager_instance)

    costs = ResourceClassCost(class_id, Credit.from_int(50))
    await repo.set_resource_class_costs(costs)
    costs2 = await repo.find_resource_class_costs(class_id)
    assert costs2 == costs

    costs = ResourceClassCost(class_id, Credit.from_int(100))
    await repo.set_resource_class_costs(costs)
    costs2 = await repo.find_resource_class_costs(class_id)
    assert costs2 == costs

    await repo.delete_resource_class_costs(class_id)
    costs3 = await repo.find_resource_pool_limits(pool_id)
    assert costs3 is None


@pytest.mark.asyncio
async def test_resource_requests_limits(app_manager_instance: DependencyManager) -> None:
    run_migrations_for_app("common")
    repo = ResourceRequestsRepo(app_manager_instance.config.db.async_session_maker)

    (pool_id, _) = await create_resource_class(app_manager_instance)

    limits = ResourcePoolLimits(pool_id, Credit.from_int(102), Credit.from_int(25))
    await repo.set_resource_pool_limits(limits)
    limits2 = await repo.find_resource_pool_limits(pool_id)
    assert limits2 == limits

    limits = ResourcePoolLimits(pool_id, Credit.from_int(500), Credit.from_int(250))
    await repo.set_resource_pool_limits(limits)
    limits2 = await repo.find_resource_pool_limits(pool_id)
    assert limits2 == limits

    await repo.delete_resource_pool_limits(pool_id)
    limits3 = await repo.find_resource_pool_limits(pool_id)
    assert limits3 == ResourcePoolLimits(pool_id, Credit.zero(), Credit.zero())

    limits4 = await repo.find_resource_pool_limits(-1)
    assert limits4 is None


@pytest.mark.asyncio
async def test_resource_request_query_by_user(app_manager_instance: DependencyManager) -> None:
    run_migrations_for_app("common")
    repo = ResourceRequestsRepo(app_manager_instance.config.db.async_session_maker)
    first_date = datetime(2026, 1, 24, 23, 55, 4, 0, tzinfo=UTC)
    interval = timedelta(minutes=15)
    await repo.insert_many(
        [
            # a pod is running
            make_resources_request(
                date=first_date + i * interval,
                interval=interval,
                cpu_request=0.2,
                memory_request="512Mi",
                user_id="user-1",
            )
            for i in range(0, 2)
        ]
        + [
            make_resources_request(
                date=first_date + i * interval,
                interval=interval,
                cpu_request=0.5,
                memory_request="256Mi",
                user_id="user-2",
            )
            for i in range(0, 2)
        ]
    )
    results = [
        x
        async for x in repo.find_usage(
            ResourceUsageQuery(since=date(2026, 1, 24), until=date(2026, 1, 25), user_id="user-2")
        )
    ]
    results.sort(key=lambda e: e.capture_date)
    assert_view_records(
        results,
        [
            {
                "capture_date": date(2026, 1, 24),
                "user_id": "user-2",
                "cpu_hours": (0.5 * (15 / 60)),
                "mem_hours": (256 * 1024 * 1024 * (15 / 60)),
                "disk_hours": None,
                "gpu_hours": None,
            },
            {
                "capture_date": date(2026, 1, 25),
                "user_id": "user-2",
                "cpu_hours": (0.5 * (15 / 60)),
                "mem_hours": (256 * 1024 * 1024 * (15 / 60)),
                "disk_hours": None,
                "gpu_hours": None,
            },
        ],
    )


@pytest.mark.asyncio
async def test_resource_request_query(app_manager_instance: DependencyManager) -> None:
    run_migrations_for_app("common")
    repo = ResourceRequestsRepo(app_manager_instance.config.db.async_session_maker)
    (pool_id, class_id) = await create_resource_class(app_manager_instance)
    await repo.set_resource_class_costs(ResourceClassCost(class_id, Credit.from_int(50)))
    first_date = datetime(2026, 1, 24, 23, 55, 4, 0, tzinfo=UTC)
    interval = timedelta(minutes=15)
    await repo.insert_many(
        [
            # a pod is running
            make_resources_request(
                date=first_date + i * interval,
                interval=interval,
                cpu_request=0.5,
                memory_request="256Mi",
                resource_class_id=class_id,
                resource_pool_id=pool_id,
            )
            for i in range(0, 2)
        ]
    )
    results = [x async for x in repo.find_usage(ResourceUsageQuery(since=date(2026, 1, 24), until=date(2026, 1, 25)))]
    results.sort(key=lambda e: e.capture_date)
    assert_view_records(
        results,
        [
            {
                "capture_date": date(2026, 1, 24),
                "user_id": "user-1",
                "resource_class_id": class_id,
                "resource_pool_id": pool_id,
                "resource_class_cost": Credit.from_int(50),
                "cpu_hours": (0.5 * (15 / 60)),
                "mem_hours": (256 * 1024 * 1024 * (15 / 60)),
                "disk_hours": None,
                "gpu_hours": None,
            },
            {
                "capture_date": date(2026, 1, 25),
                "user_id": "user-1",
                "resource_class_id": class_id,
                "resource_pool_id": pool_id,
                "resource_class_cost": Credit.from_int(50),
                "cpu_hours": (0.5 * (15 / 60)),
                "mem_hours": (256 * 1024 * 1024 * (15 / 60)),
                "disk_hours": None,
                "gpu_hours": None,
            },
        ],
    )


@pytest.mark.asyncio
async def test_resource_usage_current_week(app_manager_instance: DependencyManager) -> None:
    run_migrations_for_app("common")
    repo = ResourceRequestsRepo(app_manager_instance.config.db.async_session_maker)
    svc = app_manager_instance.resource_usage_service
    (pool_id, class_id) = await create_resource_class(app_manager_instance)
    await repo.set_resource_class_costs(ResourceClassCost(class_id, Credit.from_int(50)))
    first_date = datetime(2026, 1, 21, 21, 55, 4, 0, tzinfo=UTC)
    interval = timedelta(minutes=15)
    await repo.insert_many(
        [
            make_resources_request(
                date=first_date + i * interval,
                interval=interval,
                cpu_request=0.5,
                memory_request="256Mi",
                resource_class_id=class_id,
                resource_pool_id=pool_id,
            )
            for i in range(0, 15)
        ]
    )
    results = await svc.usage_of_running_week(pool_id, None, current_time=datetime(2026, 1, 23, 15, 20, 1, tzinfo=UTC))
    assert results.runtime_hours == 3.75  # (15 * 15) / 60
    assert results.cost == Credit.from_int(round(3.75 * 50))
    assert results.entries == 2
    assert results.first_capture == date(2026, 1, 21)
    assert results.last_capture == date(2026, 1, 22)
    assert not results.is_empty()

    results = await svc.usage_of_running_week(pool_id, None, current_time=datetime(2025, 5, 25, 13, 34, 5, tzinfo=UTC))
    assert results.is_empty()
    assert results.entries == 0
    assert results.cost == Credit.zero()


@pytest.mark.asyncio
async def test_record_resource_requests_grouping(app_manager_instance: DependencyManager) -> None:
    run_migrations_for_app("common")
    repo = ResourceRequestsRepo(app_manager_instance.config.db.async_session_maker)
    first_date = datetime(2026, 1, 22, 13, 26, 4, 0, tzinfo=UTC)
    interval = timedelta(minutes=10)
    await repo.insert_many(
        [
            # a pod is running
            make_resources_request(
                date=first_date + i * interval, interval=interval, cpu_request=0.5, memory_request="256Mi"
            )
            for i in range(0, 3)
        ]
        + [
            ## pod is down
            make_resources_request(
                date=first_date + i * interval,
                interval=interval,
                cpu_request=0.5,
                memory_request="256Mi",
                phase="Stopped",
            )
            for i in range(3, 7)
        ]
        + [
            # pod is up again for one observation
            make_resources_request(
                date=first_date + i * interval,
                interval=interval,
                cpu_request=0.5,
                memory_request="256Mi",
            )
            for i in range(7, 8)
        ]
        + [
            # was not observed for some time
            make_resources_request(
                date=first_date + i * interval,
                interval=interval,
                cpu_request=0.5,
                memory_request="256Mi",
            )
            for i in range(14, 16)
        ]
        + [
            # resource_logging is restarted after 5min
            # the next interval is only 5min, then following again 10min intervals
            make_resources_request(
                date=first_date + (i - 0.5) * interval,
                interval=interval,
                cpu_request=0.5,
                memory_request="256Mi",
            )
            for i in range(16, 19)
        ]
    )

    records = [e async for e in repo.find_view(first_date, first_date + timedelta(days=1))]
    records.sort(key=lambda e: e.capture_date)
    assert_view_records(
        records,
        [
            {
                "kind": "Pod",
                "capture_date": first_date,
                "cpu_request": ComputeCapacity.from_cores(0.5),
                "cpu_time": interval,
                "memory_request": DataSize.from_mb(256),
                "memory_time": interval,
                "disk_time": None,
            },
            {
                "kind": "Pod",
                "capture_date": first_date + interval,
                "cpu_request": ComputeCapacity.from_cores(0.5),
                "cpu_time": interval,
                "memory_request": DataSize.from_mb(256),
                "memory_time": interval,
                "disk_time": None,
            },
            {
                "kind": "Pod",
                "capture_date": first_date + 2 * interval,
                "cpu_request": ComputeCapacity.from_cores(0.5),
                "cpu_time": interval,
                "memory_request": DataSize.from_mb(256),
                "memory_time": interval,
                "disk_time": None,
            },
            # stopped pods are filtered out, the capture_interval will be used
            {
                "kind": "Pod",
                "capture_date": first_date + 7 * interval,
                "cpu_request": ComputeCapacity.from_cores(0.5),
                "cpu_time": interval,
                "memory_request": DataSize.from_mb(256),
                "memory_time": interval,
                "disk_time": None,
            },
            {
                "kind": "Pod",
                "capture_date": first_date + 14 * interval,
                "cpu_request": ComputeCapacity.from_cores(0.5),
                "cpu_time": interval,
                "memory_request": DataSize.from_mb(256),
                "memory_time": interval,
                "disk_time": None,
            },
            {
                "kind": "Pod",
                "capture_date": first_date + 15 * interval,
                "cpu_request": ComputeCapacity.from_cores(0.5),
                "cpu_time": timedelta(minutes=5),
                "memory_request": DataSize.from_mb(256),
                "memory_time": timedelta(minutes=5),
                "disk_time": None,
            },
            # here the request data collection was restarted 5min into the 10min wait interval
            # so the previous value is observed 5min, because there is already a new record
            {
                "kind": "Pod",
                "capture_date": first_date + 15.5 * interval,
                "cpu_request": ComputeCapacity.from_cores(0.5),
                "cpu_time": interval,
                "memory_request": DataSize.from_mb(256),
                "memory_time": interval,
                "disk_time": None,
            },
            {
                "kind": "Pod",
                "capture_date": first_date + 16.5 * interval,
                "cpu_request": ComputeCapacity.from_cores(0.5),
                "cpu_time": interval,
                "memory_request": DataSize.from_mb(256),
                "memory_time": interval,
                "disk_time": None,
            },
            {
                "kind": "Pod",
                "capture_date": first_date + 17.5 * interval,
                "cpu_request": ComputeCapacity.from_cores(0.5),
                "cpu_time": interval,
                "memory_request": DataSize.from_mb(256),
                "memory_time": interval,
                "disk_time": None,
            },
        ],
    )
