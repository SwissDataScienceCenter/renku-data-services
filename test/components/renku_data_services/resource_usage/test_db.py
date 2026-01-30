"""Tests for resource data."""

from datetime import UTC, date, datetime, timedelta

import pytest

from renku_data_services.data_api.dependencies import DependencyManager
from renku_data_services.migrations.core import run_migrations_for_app
from renku_data_services.resource_usage.db import ResourceRequestsRepo
from renku_data_services.resource_usage.model import ComputeCapacity, DataSize
from test.components.renku_data_services.resource_usage.helper import assert_view_records, make_resources_request


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
    results = [x async for x in repo.find_usage(start=date(2026, 1, 24), end=date(2026, 1, 25))]
    results.sort(key=lambda e: e.capture_date)
    assert_view_records(
        results,
        [
            {
                "capture_date": date(2026, 1, 24),
                "user_id": "user-1",
                "cpu_hours": (0.5 * (15 / 60)),
                "mem_hours": (256 * 1024 * 1024 * (15 / 60)),
            },
            {
                "capture_date": date(2026, 1, 25),
                "user_id": "user-1",
                "cpu_hours": (0.5 * (15 / 60)),
                "mem_hours": (256 * 1024 * 1024 * (15 / 60)),
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
