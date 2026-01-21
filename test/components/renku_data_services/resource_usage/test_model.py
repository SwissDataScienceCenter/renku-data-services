import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from box import Box
from ulid import ULID

from renku_data_services.k8s.constants import DEFAULT_K8S_CLUSTER
from renku_data_services.k8s.models import GVK, K8sObject
from renku_data_services.resource_usage.core import ResourceDataFacade
from renku_data_services.resource_usage.model import CpuUsage, MemoryUsage, RequestData, ResourcesRequest


def test_cpu_usage_add() -> None:
    cu1 = CpuUsage.from_str("189963n") or CpuUsage.zero()
    cu2 = CpuUsage.from_str("889963n") or CpuUsage.zero()
    res = CpuUsage.from_nano_cores(889963 + 189963)
    assert (cu1 + cu2) == res


@pytest.mark.parametrize(
    "value, num, factor",
    [
        (CpuUsage.from_nano_cores(12345), 12345, 10**9),
        (CpuUsage.from_micro_cores(1212), 1212, 10**6),
        (CpuUsage.from_milli_cores(520), 520, 10**3),
    ],
)
def test_cpu_usage_from_cores(value, num, factor) -> None:
    expect = CpuUsage(value=Decimal(str(num / factor)))
    assert value == expect


@pytest.mark.parametrize(
    "value, nano, micro, milli, cores",
    [
        (CpuUsage.from_nano_cores(12345), 12345, 12.345, 0.012345, 0.000012345),
        (CpuUsage.from_micro_cores(1212), 1212000, 1212, 1.212, 0.001212),
        (CpuUsage.from_milli_cores(520), 520000000, 520000, 520, 0.52),
    ],
)
def test_cpu_usage_accessors(value: CpuUsage, nano: float, micro: float, milli: float, cores: float) -> None:
    assert value.nano_cores == nano
    assert value.micro_cores == pytest.approx(micro, abs=1e-9)
    assert value.milli_cores == milli
    assert value.cores == cores


def test_memory_usage_from_str() -> None:
    assert MemoryUsage.from_str("189Mi") == MemoryUsage.from_bytes(189 * 1024 * 1024)
    assert MemoryUsage.from_str("2455") == MemoryUsage.from_bytes(2455)


def test_memory_usage_add() -> None:
    mu1 = MemoryUsage.from_str("189Mi") or MemoryUsage.zero()
    mu2 = MemoryUsage.from_str("889963") or MemoryUsage.zero()
    res = MemoryUsage.from_bytes((189 * 1024 * 1024) + 889963)
    assert (mu1 + mu2) == res


def test_memory_usage_from() -> None:
    assert MemoryUsage.from_kb(0.4501246) == MemoryUsage(value=Decimal("460.9275904"))


def test_request_data_add() -> None:
    r1 = RequestData(cpu=CpuUsage.from_milli_cores(250), memory=MemoryUsage.from_mb(512), gpu=CpuUsage.zero())
    r2 = RequestData(cpu=CpuUsage.from_milli_cores(200), memory=MemoryUsage.from_mb(250), gpu=CpuUsage.zero())
    expect = RequestData(cpu=CpuUsage.from_milli_cores(450), memory=MemoryUsage.from_mb(762), gpu=CpuUsage.zero())
    assert (r1 + r2) == expect


def test_resource_data_facade() -> None:
    ams_json = {}
    with open(Path(__file__).parent / "ams.json") as f:
        ams_json = json.load(f)
    ams = K8sObject(
        name="xyz",
        namespace="renku",
        cluster=DEFAULT_K8S_CLUSTER,
        gvk=GVK(kind="Pod", version="v1"),
        manifest=Box(ams_json),
    )

    pod_json = {}
    with open(Path(__file__).parent / "pod.json") as f:
        pod_json = json.load(f)

    pod = K8sObject(
        name="xyz",
        namespace="renku",
        cluster=DEFAULT_K8S_CLUSTER,
        gvk=GVK(kind="Pod", version="v1"),
        manifest=Box(pod_json),
    )
    pd = ResourceDataFacade(pod)
    ad = ResourceDataFacade(ams)
    date = datetime.now(UTC)

    r1 = pd.to_resources_request(DEFAULT_K8S_CLUSTER, date)
    assert r1 == ResourcesRequest(
        namespace=pd.namespace,
        pod_name=pd.name,
        capture_date=date,
        cluster_id=DEFAULT_K8S_CLUSTER,
        user_id=pd.user_id,
        project_id=pd.project_id,
        launcher_id=pd.launcher_id,
        resource_class_id=pd.resource_class_id,
        data=pd.requested_data,
    )
    r2 = ad.to_resources_request(DEFAULT_K8S_CLUSTER, date)
    assert r2 == ResourcesRequest(
        namespace=ad.namespace,
        pod_name=ad.name,
        capture_date=date,
        cluster_id=DEFAULT_K8S_CLUSTER,
        user_id=ad.user_id,
        project_id=ad.project_id,
        launcher_id=ad.launcher_id,
        resource_class_id=ad.resource_class_id,
        data=ad.requested_data,
    )
    assert ad.user_id, "user_id not provided"
    assert ad.requested_data == RequestData.zero()
    assert ad.project_id == ULID.from_str("01KCVFX9BVTADB8SGHN7RJFJAP")
    assert ad.launcher_id == ULID.from_str("01KCVFZW2N6S20JAY67K30JNJ7")
    assert ad.resource_class_id == 4
    assert not ad.session_instance_id

    assert not pd.user_id
    assert not pd.project_id
    assert not pd.launcher_id
    assert not pd.resource_class_id
    assert pd.requested_data == RequestData(
        cpu=CpuUsage.from_cores(0.54), memory=MemoryUsage.from_mb(1056), gpu=CpuUsage.zero()
    )
    assert pd.session_instance_id == "eike-kettner-962026d34ba4"

    print(pd.to_resources_request(DEFAULT_K8S_CLUSTER, date))
    print(ad.to_resources_request(DEFAULT_K8S_CLUSTER, date))
