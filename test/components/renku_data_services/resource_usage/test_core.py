"""Test core functions."""

from datetime import UTC, datetime

import pytest
from ulid import ULID

from renku_data_services.data_api.dependencies import DependencyManager
from renku_data_services.k8s.constants import DEFAULT_K8S_CLUSTER
from renku_data_services.migrations.core import run_migrations_for_app
from renku_data_services.resource_usage.core import (
    ResourceRequestsFetchProto,
    ResourceRequestsRepo,
    ResourcesRequestRecorder,
)
from renku_data_services.resource_usage.model import ComputeCapacity, DataSize, RequestData, ResourcesRequest
from renku_data_services.resource_usage.orm import ResourceRequestsLogORM


class TestResourceRequestsFetch(ResourceRequestsFetchProto):
    def __init__(self, data: list[ResourcesRequest]) -> None:
        self.data = data

    async def get_resources_requests(
        self, namespace: str, with_labels: dict[str, str] | None = None
    ) -> dict[str, ResourcesRequest]:
        """Return the resources requests of all pods."""
        return {e.id: e for e in self.data}


@pytest.mark.asyncio
async def test_record_empty_resource_requests(app_manager_instance: DependencyManager) -> None:
    run_migrations_for_app("common")

    fetch = TestResourceRequestsFetch([])
    repo = ResourceRequestsRepo(app_manager_instance.config.db.async_session_maker)
    recorder = ResourcesRequestRecorder(repo, fetch)
    await recorder.record_resource_requests("whatever")
    all = [item async for item in repo.find_all()]
    assert len(all) == 0


# import logging
# logging.basicConfig()
# logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)


@pytest.mark.asyncio
async def test_record_resource_requests(app_manager_instance: DependencyManager) -> None:
    run_migrations_for_app("common")
    dt = datetime.now(UTC).replace(microsecond=0)
    data = [
        ResourcesRequest(
            namespace="renku",
            name="pod1",
            uid="xyz-898-dec",
            kind="Pod",
            phase="Running",
            capture_date=dt,
            cluster_id=DEFAULT_K8S_CLUSTER,
            user_id="exyz",
            project_id=ULID(),
            launcher_id=None,
            resource_class_id=4,
            resource_pool_id=16,
            since=datetime(2025, 1, 15, 13, 25, 15, 0, UTC),
            data=RequestData(
                cpu=ComputeCapacity.from_milli_cores(250),
                memory=DataSize.from_mb(512),
                gpu=ComputeCapacity.zero(),
                disk=DataSize.zero(),
            ),
        ),
        ResourcesRequest(
            namespace="renku",
            name="pod2",
            uid="abc-def-123",
            kind="Pod",
            phase="Running",
            capture_date=dt,
            cluster_id=DEFAULT_K8S_CLUSTER,
            user_id="exyz",
            project_id=ULID(),
            launcher_id=None,
            resource_class_id=4,
            resource_pool_id=16,
            since=datetime(2025, 1, 15, 11, 13, 54, 0, UTC),
            data=RequestData(
                cpu=ComputeCapacity.from_milli_cores(150),
                memory=DataSize.from_mb(256),
                gpu=ComputeCapacity.from_milli_cores(100),
                disk=DataSize.from_mb(1202),
            ),
        ),
    ]

    fetch = TestResourceRequestsFetch(data)
    repo = ResourceRequestsRepo(app_manager_instance.config.db.async_session_maker)
    recorder = ResourcesRequestRecorder(repo, fetch)
    await recorder.record_resource_requests("whatever")
    all = [item async for item in repo.find_all()]
    assert len(all) == 2
    assert {e.name for e in all} == {"pod1", "pod2"}
    for item in all:
        if item.name == "pod1":
            obj = ResourceRequestsLogORM.from_resources_request(data[0])
            obj.id = item.id
            assert item == obj
        if item.name == "pod2":
            obj = ResourceRequestsLogORM.from_resources_request(data[1])
            obj.id = item.id
            assert item == obj
