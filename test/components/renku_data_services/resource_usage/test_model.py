import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from box import Box
from ulid import ULID

from renku_data_services.k8s.constants import DEFAULT_K8S_CLUSTER
from renku_data_services.k8s.models import GVK, K8sObject
from renku_data_services.resource_usage.core import ResourceDataFacade
from renku_data_services.resource_usage.model import ComputeCapacity, DataSize, RequestData, ResourcesRequest


def test_cpu_usage_add() -> None:
    cu1 = ComputeCapacity.from_str("189963n") or ComputeCapacity.zero()
    cu2 = ComputeCapacity.from_str("889963n") or ComputeCapacity.zero()
    res = ComputeCapacity.from_nano_cores(889963 + 189963)
    assert (cu1 + cu2) == res


@pytest.mark.parametrize(
    "value, num, factor",
    [
        (ComputeCapacity.from_nano_cores(12345), 12345, 10**9),
        (ComputeCapacity.from_micro_cores(1212), 1212, 10**6),
        (ComputeCapacity.from_milli_cores(520), 520, 10**3),
    ],
)
def test_cpu_usage_from_cores(value, num, factor) -> None:
    expect = ComputeCapacity(value=Decimal(str(num / factor)))
    assert value == expect


@pytest.mark.parametrize(
    "value, nano, micro, milli, cores",
    [
        (ComputeCapacity.from_nano_cores(12345), 12345, 12.345, 0.012345, 0.000012345),
        (ComputeCapacity.from_micro_cores(1212), 1212000, 1212, 1.212, 0.001212),
        (ComputeCapacity.from_milli_cores(520), 520000000, 520000, 520, 0.52),
    ],
)
def test_cpu_usage_accessors(value: ComputeCapacity, nano: float, micro: float, milli: float, cores: float) -> None:
    assert value.nano_cores == nano
    assert value.micro_cores == pytest.approx(micro, abs=1e-9)
    assert value.milli_cores == milli
    assert value.cores == cores


def test_memory_usage_from_str() -> None:
    assert DataSize.from_str("189Mi") == DataSize.from_bytes(189 * 1024 * 1024)
    assert DataSize.from_str("2455") == DataSize.from_bytes(2455)


def test_memory_usage_add() -> None:
    mu1 = DataSize.from_str("189Mi") or DataSize.zero()
    mu2 = DataSize.from_str("889963") or DataSize.zero()
    res = DataSize.from_bytes((189 * 1024 * 1024) + 889963)
    assert (mu1 + mu2) == res


def test_memory_usage_from() -> None:
    assert DataSize.from_kb(0.4501246) == DataSize(value=Decimal("460.9275904"))


def test_request_data_add() -> None:
    r1 = RequestData(
        cpu=ComputeCapacity.from_milli_cores(250),
        memory=DataSize.from_mb(512),
        gpu=ComputeCapacity.zero(),
        disk=DataSize.from_mb(120),
    )
    r2 = RequestData(
        cpu=ComputeCapacity.from_milli_cores(200),
        memory=DataSize.from_mb(250),
        gpu=ComputeCapacity.zero(),
        disk=DataSize.from_mb(1000),
    )
    expect = RequestData(
        cpu=ComputeCapacity.from_milli_cores(450),
        memory=DataSize.from_mb(762),
        gpu=ComputeCapacity.zero(),
        disk=DataSize.from_mb(1120),
    )
    assert (r1 + r2) == expect


def load_manifest(name: str) -> Box:
    manifest_json = {}
    with open(Path(__file__).parent / name) as f:
        manifest_json = json.load(f)
    return Box(manifest_json)


def test_resource_requests_to_zero() -> None:
    date = datetime.now(UTC)
    r1 = ResourcesRequest(
        namespace="renku",
        name="pod1",
        uid="xyz-898-dec",
        kind="Pod",
        api_version="v1",
        phase="Running",
        capture_date=date,
        capture_interval=timedelta(seconds=500),
        cluster_id=DEFAULT_K8S_CLUSTER,
        user_id="exyz",
        project_id=ULID(),
        launcher_id=None,
        resource_class_id=4,
        resource_pool_id=16,
        since=datetime(2025, 1, 15, 13, 25, 15, 0, UTC),
        gpu_slice=None,
        data=RequestData(
            cpu=ComputeCapacity.from_milli_cores(250),
            memory=DataSize.from_mb(512),
            gpu=ComputeCapacity.zero(),
            disk=DataSize.zero(),
        ),
    )
    r0 = r1.to_zero()
    assert r1.namespace == r0.namespace
    assert r1.name == r0.name
    assert r1.uid == r0.uid
    assert r1.kind == r0.kind
    assert r1.phase == r0.phase
    assert r1.capture_date == r0.capture_date
    assert r1.cluster_id == r0.cluster_id
    assert r1.user_id == r0.user_id
    assert r1.project_id == r0.project_id
    assert r1.launcher_id == r0.launcher_id
    assert r1.resource_class_id == r0.resource_class_id
    assert r1.resource_pool_id == r0.resource_pool_id
    assert r1.since == r0.since
    assert r0.data == RequestData.zero()


def test_resource_data_facade() -> None:
    ams = K8sObject(
        name="xyz",
        namespace="renku",
        cluster=DEFAULT_K8S_CLUSTER,
        gvk=GVK(kind="Pod", version="v1"),
        manifest=load_manifest("ams.json"),
    )
    pod = K8sObject(
        name="xyz2",
        namespace="renku",
        cluster=DEFAULT_K8S_CLUSTER,
        gvk=GVK(kind="Pod", version="v1"),
        manifest=load_manifest("pod.json"),
    )

    pvc = K8sObject(
        name="xyz3",
        namespace="renku",
        cluster=DEFAULT_K8S_CLUSTER,
        gvk=GVK(kind="PersistentVolumeClaim", version="v1"),
        manifest=load_manifest("pvc.json"),
    )

    pd = ResourceDataFacade(pod)
    ad = ResourceDataFacade(ams)
    pv = ResourceDataFacade(pvc)
    date = datetime.now(UTC)
    interval = timedelta(seconds=600)

    r1 = pd.to_resources_request(DEFAULT_K8S_CLUSTER, date, interval)
    assert r1 == ResourcesRequest(
        namespace=pd.namespace,
        name=pd.name,
        uid=pd.uid,
        kind=pd.kind,
        api_version=pd.api_version,
        phase=pd.phase,
        capture_date=date,
        capture_interval=interval,
        cluster_id=DEFAULT_K8S_CLUSTER,
        user_id=pd.user_id,
        project_id=pd.project_id,
        launcher_id=pd.launcher_id,
        resource_class_id=pd.resource_class_id,
        resource_pool_id=pd.resource_pool_id,
        since=pd.start_or_creation_time,
        gpu_slice=None,
        data=pd.requested_data,
    )
    r2 = ad.to_resources_request(DEFAULT_K8S_CLUSTER, date, interval)
    assert r2 == ResourcesRequest(
        namespace=ad.namespace,
        name=ad.name,
        uid=ad.uid,
        kind=ad.kind,
        api_version=ad.api_version,
        phase=ad.phase,
        capture_date=date,
        capture_interval=interval,
        cluster_id=DEFAULT_K8S_CLUSTER,
        user_id=ad.user_id,
        project_id=ad.project_id,
        launcher_id=ad.launcher_id,
        resource_class_id=ad.resource_class_id,
        resource_pool_id=ad.resource_pool_id,
        since=ad.start_or_creation_time,
        gpu_slice=None,
        data=ad.requested_data,
    )
    r3 = pv.to_resources_request(DEFAULT_K8S_CLUSTER, date, interval)
    assert r3 == ResourcesRequest(
        namespace=pv.namespace,
        name=pv.name,
        uid=pv.uid,
        kind=pv.kind,
        api_version=pv.api_version,
        phase=pv.phase,
        capture_date=date,
        capture_interval=interval,
        cluster_id=DEFAULT_K8S_CLUSTER,
        user_id=pv.user_id,
        project_id=pv.project_id,
        launcher_id=pv.launcher_id,
        resource_class_id=pv.resource_class_id,
        resource_pool_id=pv.resource_pool_id,
        since=pv.start_or_creation_time,
        gpu_slice=None,
        data=pv.requested_data,
    )

    assert ad.user_id, "user_id not provided"
    assert ad.requested_data == RequestData.zero()
    assert ad.project_id == ULID.from_str("01KCVFX9BVTADB8SGHN7RJFJAP")
    assert ad.launcher_id == ULID.from_str("01KCVFZW2N6S20JAY67K30JNJ7")
    assert ad.resource_class_id == 4
    assert not ad.session_instance_id
    assert ad.uid == "3f51dcde-04fa-4a50-a887-a95ec0887145"
    assert ad.kind == "AmaltheaSession"

    assert not pd.user_id
    assert not pd.project_id
    assert not pd.launcher_id
    assert not pd.resource_class_id
    assert pd.uid == "aa36ed58-0484-4e93-8daa-1212263dbc47"
    assert pd.start_or_creation_time == datetime(2026, 1, 20, 13, 25, 54, 0, UTC)
    assert pd.phase == "Running"
    assert pd.kind == "Pod"
    assert pd.requested_data == RequestData(
        cpu=ComputeCapacity.from_cores(0.54),
        memory=DataSize.from_mb(1056),
        gpu=ComputeCapacity.zero(),
        disk=DataSize.zero(),
    )
    assert pd.session_instance_id == "eike-kettner-962026d34ba4"

    assert pv.start_or_creation_time == datetime(2026, 1, 14, 14, 42, 4, 0, UTC)
    assert pv.phase == "Bound"
    assert pv.status_storage == DataSize.from_mb(1024)
    assert pv.kind == "PersistentVolumeClaim"
