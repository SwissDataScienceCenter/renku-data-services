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
from renku_data_services.resource_usage.model import CpuUsage, MemoryUsage, RequestData, ResourcesRequest
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


@pytest.mark.asyncio
async def test_record_resource_requests(app_manager_instance: DependencyManager) -> None:
    run_migrations_for_app("common")
    dt = datetime.now(UTC).replace(microsecond=0)
    data = [
        ResourcesRequest(
            namespace="renku",
            pod_name="pod1",
            pod_uid="xyz-898-dec",
            capture_date=dt,
            cluster_id=DEFAULT_K8S_CLUSTER,
            user_id="exyz",
            project_id=ULID(),
            launcher_id=None,
            resource_class_id=4,
            data=RequestData(cpu=CpuUsage.from_milli_cores(250), memory=MemoryUsage.from_mb(512), gpu=CpuUsage.zero()),
        ),
        ResourcesRequest(
            namespace="renku",
            pod_name="pod2",
            pod_uid="abc-def-123",
            capture_date=dt,
            cluster_id=DEFAULT_K8S_CLUSTER,
            user_id="exyz",
            project_id=ULID(),
            launcher_id=None,
            resource_class_id=4,
            data=RequestData(
                cpu=CpuUsage.from_milli_cores(150), memory=MemoryUsage.from_mb(256), gpu=CpuUsage.from_milli_cores(100)
            ),
        ),
    ]

    fetch = TestResourceRequestsFetch(data)
    repo = ResourceRequestsRepo(app_manager_instance.config.db.async_session_maker)
    recorder = ResourcesRequestRecorder(repo, fetch)
    await recorder.record_resource_requests("whatever")
    all = [item async for item in repo.find_all()]
    assert len(all) == 2
    assert {e.pod_name for e in all} == {"pod1", "pod2"}
    for item in all:
        if item.pod_name == "pod1":
            obj = ResourceRequestsLogORM.from_resources_request(data[0])
            obj.id = item.id
            assert item == obj
        if item.pod_name == "pod2":
            obj = ResourceRequestsLogORM.from_resources_request(data[1])
            obj.id = item.id
            assert item == obj
