"""Some helper functions for testing."""

from datetime import datetime, timedelta

from pytest import fail
from ulid import ULID

from renku_data_services.k8s.constants import DEFAULT_K8S_CLUSTER
from renku_data_services.resource_usage.model import ComputeCapacity, DataSize, RequestData, ResourcesRequest


def make_resources_request(
    date: datetime,
    user_id: str = "user-1",
    cpu_request: ComputeCapacity | float | str | None = None,
    memory_request: DataSize | float | str | None = None,
    disk_request: DataSize | float | str | None = None,
    gpu_request: ComputeCapacity | float | str | None = None,
    gpu_slice: float | None = None,
    phase: str | None = None,
    interval: timedelta = timedelta(seconds=600),
    project_id: ULID | None = None,
    launcher_id: ULID | None = None,
    resource_class_id: int = 4,
    resource_pool_id: int = 5,
    namespace: str = "renku",
    name: str | None = None,
    kind: str | None = None,
    uid: str = "uid1",
    version: str = "v1",
) -> ResourcesRequest:
    obj_kind = (
        kind
        if kind is not None
        else "Pod"
        if cpu_request is not None or memory_request is not None
        else "PersistentVolumeClaim"
    )
    obj_name = name if name is not None else "pod1" if obj_kind == "Pod" else "pvc1"
    obj_phase = phase if phase is not None else "Running" if obj_kind == "Pod" else "Mounted"
    ccpu: ComputeCapacity | None = None
    if isinstance(cpu_request, ComputeCapacity):
        ccpu = cpu_request
    elif isinstance(cpu_request, float):
        ccpu = ComputeCapacity.from_cores(cpu_request)
    elif isinstance(cpu_request, str):
        ccpu = ComputeCapacity.from_str(cpu_request)

    mmreq: DataSize | None = None
    match memory_request:
        case DataSize() as s:
            mmreq = s
        case float() as n:
            mmreq = DataSize.from_mb(n)
        case str() as s:
            mmreq = DataSize.from_str(s)

    ggpu: ComputeCapacity | None = None
    match gpu_request:
        case ComputeCapacity() as c:
            ggpu = c
        case float() as n:
            ggpu = ComputeCapacity.from_cores(n)
        case str() as s:
            ggpu = ComputeCapacity.from_str(s)

    ddisk: DataSize | None = None
    match disk_request:
        case DataSize() as s:
            ddisk = s
        case float() as n:
            ddisk = DataSize.from_mb(n)
        case str() as s:
            ddisk = DataSize.from_str(s)

    return ResourcesRequest(
        namespace=namespace,
        name=obj_name,
        uid=uid,
        kind=obj_kind,
        api_version=version,
        phase=obj_phase,
        capture_date=date,
        capture_interval=interval,
        cluster_id=DEFAULT_K8S_CLUSTER,
        user_id=user_id,
        project_id=project_id if project_id else ULID.from_str("01KG702QKR3A34MTBY10GZECZM"),
        launcher_id=launcher_id if launcher_id else ULID.from_str("01KG7052Z2JKFCP1ZQ466TXQNZ"),
        resource_class_id=resource_class_id,
        resource_pool_id=resource_pool_id,
        since=None,
        gpu_slice=gpu_slice if gpu_slice is not None else 0.5 if gpu_request is not None else None,
        gpu_product="NVIDIA-A100-80GB-PCIe-MIG-2g.20gb" if gpu_request is not None else None,
        data=RequestData(cpu=ccpu, memory=mmreq, gpu=ggpu, disk=ddisk),
    )


def assert_view_records(records, list_of_attrs, allow_fewer: bool = False) -> None:
    if not allow_fewer and len(records) != len(list_of_attrs):
        fail("Records and given list is not of same size")

    size = min(len(records), len(list_of_attrs))
    for i in range(0, size):
        rs = records[i].__dict__
        re = list_of_attrs[i]
        for key, value in re.items():
            rs_val = rs.get(key)
            assert rs_val == value, f"{key}: {type(rs_val)} {rs_val} (given) is not {type(value)} {value} (expected)!"
