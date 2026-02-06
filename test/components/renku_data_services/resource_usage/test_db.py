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
    ResourceUsageQuery,
)
from renku_data_services.resource_usage.orm import ResourcePoolLimits
from test.components.renku_data_services.resource_usage.helper import assert_view_records, make_resources_request


@pytest.mark.asyncio
async def test_resource_class_costs_query(app_manager_instance: DependencyManager) -> None:
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
            )
            for i in range(18, 21)
        ]
    )


@pytest.mark.asyncio
async def test_resource_class_costs(app_manager_instance: DependencyManager) -> None:
    run_migrations_for_app("common")
    repo = ResourceRequestsRepo(app_manager_instance.config.db.async_session_maker)

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

    costs = ResourceClassCost(class_id, 50)
    await repo.set_resource_class_costs(costs)
    costs2 = await repo.find_resource_class_costs(class_id)
    assert costs2 == costs

    costs = ResourceClassCost(class_id, 100)
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

    async with app_manager_instance.config.db.async_session_maker() as session, session.begin():
        stmt = sa.text("""
        insert into resource_pools.resource_pools (name,quota,"default","public")
        values ('test', '1',true,true)
        returning id""")
        res = await session.execute(stmt)
        pool_id = res.scalar_one()

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
    assert limits3 is None


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
    first_date = datetime(2026, 1, 24, 23, 55, 4, 0, tzinfo=UTC)
    interval = timedelta(minutes=15)
    await repo.insert_many(
        [
            # a pod is running
            make_resources_request(
                date=first_date + i * interval, interval=interval, cpu_request=0.5, memory_request="256Mi"
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
                "cpu_hours": (0.5 * (15 / 60)),
                "mem_hours": (256 * 1024 * 1024 * (15 / 60)),
                "disk_hours": None,
                "gpu_hours": None,
            },
            {
                "capture_date": date(2026, 1, 25),
                "user_id": "user-1",
                "cpu_hours": (0.5 * (15 / 60)),
                "mem_hours": (256 * 1024 * 1024 * (15 / 60)),
                "disk_hours": None,
                "gpu_hours": None,
            },
        ],
    )


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
