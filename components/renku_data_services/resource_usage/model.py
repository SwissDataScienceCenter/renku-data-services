"""Data model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from math import floor
from typing import Any, cast

from dateutil.parser import parse as parse_datetime
from kubernetes.utils.quantity import parse_quantity
from ulid import ULID

from renku_data_services.k8s.constants import ClusterId
from renku_data_services.k8s.models import K8sObject


@dataclass(frozen=True)
class DataSize:
    """Data size in bytes."""

    value: Decimal

    @property
    def bytes(self) -> float:
        """Return bytes as float."""
        return float(self.value)

    @property
    def kilobyte(self) -> float:
        """Convert to kilobyte."""
        return float(self.value / 1024)

    @property
    def megabyte(self) -> float:
        """Convert to megabyte."""
        return self.kilobyte / 1024

    def __str__(self) -> str:
        return str(self.value)

    @classmethod
    def from_str(cls, s: str) -> DataSize | None:
        """Parse a quantity string."""
        try:
            return DataSize(value=parse_quantity(s))
        except ValueError:
            return None

    @classmethod
    def from_bytes(cls, bytes: float | Decimal) -> DataSize:
        """Create an instance given bytes."""
        return cls.__from_n_bytes(bytes, 1)

    @classmethod
    def from_kb(cls, kb: float | Decimal) -> DataSize:
        """Create an instance given kilobytes."""
        return cls.__from_n_bytes(kb, 1024)

    @classmethod
    def from_mb(cls, mb: float | Decimal) -> DataSize:
        """Create an instance given mega bytes."""
        return cls.__from_n_bytes(mb, 1024 * 1024)

    @classmethod
    def __from_n_bytes(cls, n: float | Decimal, factor: int) -> DataSize:
        """Create an instance given mega bytes."""
        if isinstance(n, Decimal):
            return DataSize(n * factor)
        else:
            return DataSize(Decimal(str(n * factor)))

    @classmethod
    def zero(cls) -> DataSize:
        """The zero value."""
        return DataSize(value=Decimal(0))

    def __add__(self, other: Any) -> DataSize:
        if isinstance(other, DataSize):
            return DataSize(self.value + other.value)
        else:
            raise Exception("")


@dataclass(frozen=True)
class ComputeCapacity:
    """Cpu usage data in 'cores'."""

    value: Decimal

    @property
    def cores(self) -> float:
        """Return cores as float."""
        return float(self.value)

    @property
    def nano_cores(self) -> float:
        """Return the value in nanocores."""
        return self.cores * (10**9)

    @property
    def micro_cores(self) -> float:
        """Return the value in millicores."""
        return self.cores * (10**6)

    @property
    def milli_cores(self) -> float:
        """Return the value in millicores."""
        return self.cores * (10**3)

    def __add__(self, other: Any) -> ComputeCapacity:
        if isinstance(other, ComputeCapacity):
            return ComputeCapacity(self.value + other.value)
        else:
            raise Exception(f"Cannot add value of type {type(other)} to CpuUsage")

    def __str__(self) -> str:
        return str(self.value)

    @classmethod
    def from_str(cls, s: str) -> ComputeCapacity | None:
        """Parses a quantity string."""
        try:
            return ComputeCapacity(value=parse_quantity(s))
        except ValueError:
            return None

    @classmethod
    def from_nano_cores(cls, n: float | Decimal) -> ComputeCapacity:
        """Create an instance from nano cores."""
        return cls.__from_frac_cores(n, 10**9)

    @classmethod
    def from_micro_cores(cls, n: float | Decimal) -> ComputeCapacity:
        """Create an instance from nano cores."""
        return cls.__from_frac_cores(n, 10**6)

    @classmethod
    def from_milli_cores(cls, n: float | Decimal) -> ComputeCapacity:
        """Create an instance from nano cores."""
        return cls.__from_frac_cores(n, 10**3)

    @classmethod
    def from_cores(cls, n: float | Decimal) -> ComputeCapacity:
        """Create an instance from cores."""
        return cls.__from_frac_cores(n, 1)

    @classmethod
    def __from_frac_cores(cls, n: float | Decimal, f: int) -> ComputeCapacity:
        """Create an instance from nano cores."""
        if isinstance(n, Decimal):
            return ComputeCapacity(n / f)
        else:
            return ComputeCapacity(Decimal(str(n / f)))

    @classmethod
    def zero(cls) -> ComputeCapacity:
        """The zero value."""
        return ComputeCapacity(value=Decimal(0))


@dataclass
class RequestData:
    """Contains resource requests quantities."""

    cpu: ComputeCapacity | None
    gpu: ComputeCapacity | None
    memory: DataSize | None
    disk: DataSize | None

    def __str__(self) -> str:
        return f"cpu={self.cpu},mem={self.memory},gpu={self.gpu}"

    def __add__(self, other: Any) -> RequestData:
        if isinstance(other, RequestData):
            return RequestData(
                cpu=(self.cpu or ComputeCapacity.zero()) + (other.cpu or ComputeCapacity.zero())
                if self.cpu is not None or other.cpu is not None
                else None,
                gpu=(self.gpu or ComputeCapacity.zero()) + (other.gpu or ComputeCapacity.zero())
                if self.gpu is not None or other.gpu is not None
                else None,
                memory=(self.memory or DataSize.zero()) + (other.memory or DataSize.zero())
                if self.memory is not None or other.memory is not None
                else None,
                disk=(self.disk or DataSize.zero()) + (other.disk or DataSize.zero())
                if self.disk is not None or other.disk is not None
                else None,
            )
        else:
            raise Exception(f"Cannot add value of type {type(other)} to RequestData")

    def with_disk(self, disk: DataSize | None) -> RequestData:
        """Return a copy with disk set."""
        return RequestData(cpu=self.cpu, gpu=self.gpu, memory=self.memory, disk=disk)

    def is_empty(self) -> bool:
        """Returns true when all values are None."""
        return self.cpu is None and self.gpu is None and self.memory is None and self.disk is None

    def is_non_empty(self) -> bool:
        """Returns true when at least one value is not None."""
        return not self.is_empty()

    @classmethod
    def all_zero(cls) -> RequestData:
        """Return a value with 0."""
        return RequestData(
            cpu=ComputeCapacity.zero(), gpu=ComputeCapacity.zero(), memory=DataSize.zero(), disk=DataSize.zero()
        )

    @classmethod
    def empty(cls) -> RequestData:
        """Return a value with None."""
        return RequestData(cpu=None, gpu=None, memory=None, disk=None)


@dataclass
class ResourcesRequest:
    """Data structure capturing request to resources."""

    namespace: str
    name: str
    uid: str
    kind: str
    api_version: str
    phase: str
    capture_date: datetime
    capture_interval: timedelta
    cluster_id: ClusterId | None
    user_id: str | None
    project_id: ULID | None
    launcher_id: ULID | None
    resource_class_id: int | None
    resource_pool_id: int | None
    since: datetime | None
    gpu_slice: float | None
    data: RequestData

    @property
    def id(self) -> str:
        """Return an identifier string."""
        cid = self.cluster_id or "default-cluster"
        return (
            f"{cid}/{self.namespace}/"
            f"{self.uid}/"
            f"{self.name}/"
            f"{self.kind}/"
            f"{self.api_version}/"
            f"{self.phase}/"
            f"{self.user_id}/"
            f"{self.project_id}/"
            f"{self.launcher_id}/"
            f"{self.resource_class_id}/"
            f"{self.resource_pool_id}/"
            f"{self.since}/"
            f"{self.gpu_slice}/"
            f"@{self.capture_date}/{self.capture_interval}"
        )

    def to_empty(self) -> ResourcesRequest:
        """Return a new value with all numbers set to None."""
        return ResourcesRequest(
            namespace=self.namespace,
            name=self.name,
            uid=self.uid,
            phase=self.phase,
            kind=self.kind,
            api_version=self.api_version,
            capture_date=self.capture_date,
            capture_interval=self.capture_interval,
            cluster_id=self.cluster_id,
            user_id=self.user_id,
            project_id=self.project_id,
            launcher_id=self.launcher_id,
            resource_class_id=self.resource_class_id,
            resource_pool_id=self.resource_pool_id,
            since=self.since,
            gpu_slice=self.gpu_slice,
            data=RequestData.empty(),
        )

    def add(self, other: ResourcesRequest) -> ResourcesRequest:
        """Adds the values of other to this returning a new value. Returns this if both ids do not match."""
        if other.id == self.id:
            return ResourcesRequest(
                namespace=self.namespace,
                name=self.name,
                uid=self.uid,
                kind=self.kind,
                api_version=self.api_version,
                phase=self.phase,
                capture_date=self.capture_date,
                capture_interval=self.capture_interval,
                cluster_id=self.cluster_id,
                user_id=self.user_id,
                project_id=self.project_id,
                launcher_id=self.launcher_id,
                resource_class_id=self.resource_class_id,
                resource_pool_id=self.resource_pool_id,
                since=self.since,
                gpu_slice=self.gpu_slice,
                data=self.data + other.data,
            )
        else:
            return self

    def __str__(self) -> str:
        return f"{self.id}: {self.data}"


@dataclass
class ResourceDataFacade:
    """Wraps a k8s session, pod or pvc extracting certain data that should be stored."""

    pod: K8sObject

    def __get_annotation(self, name: str) -> str | None:
        value = self.pod.manifest.get("metadata", {}).get("annotations", {}).get(name)
        return cast(str, value) if value is not None else None

    def __get_label(self, name: str) -> str | None:
        value = self.pod.manifest.get("metadata", {}).get("labels", {}).get(name)
        return cast(str, value) if value is not None else None

    @property
    def kind(self) -> str:
        """Return the kind."""
        return cast(str, self.pod.manifest.kind)

    @property
    def api_version(self) -> str:
        """Return the apiVersion field."""
        return cast(str, self.pod.manifest.get("apiVersion"))

    @property
    def resource_request_storage(self) -> DataSize | None:
        """Return the storage spec of a pvc."""
        value = self.pod.manifest.get("spec", {}).get("resources", {}).get("requests", {}).get("storage")
        return DataSize.from_str(str(value)) if value is not None else None

    @property
    def status_storage(self) -> DataSize | None:
        """Return the storage spec of a pvc."""
        value = self.pod.manifest.get("status", {}).get("capacity", {}).get("storage")
        return DataSize.from_str(str(value)) if value is not None else None

    @property
    def name(self) -> str:
        """Return the pod name."""
        return cast(str, self.pod.manifest.metadata.name)

    @property
    def session_instance_id(self) -> str | None:
        """Get the session instance name if this is a pod started for a session."""
        k8s_name = self.__get_label("app.kubernetes.io/name")
        if k8s_name == "AmaltheaSession":
            return self.__get_label("app.kubernetes.io/instance")
        else:
            return None

    @property
    def uid(self) -> str:
        """Return the k8s uid of the object."""
        return cast(str, self.pod.manifest.metadata.uid)

    @property
    def user_id(self) -> str | None:
        """Return the user_id asscociated to this resource."""
        return self.__get_label("renku.io/safe-username")

    @property
    def project_id(self) -> ULID | None:
        """Return the project id if this is a pod associated to a session."""
        id = self.__get_annotation("renku.io/project_id")
        return ULID.from_str(id) if id is not None else None

    @property
    def launcher_id(self) -> ULID | None:
        """Return the launcher id if this is a pod associated to a session."""
        id = self.__get_annotation("renku.io/launcher_id")
        return ULID.from_str(id) if id is not None else None

    @property
    def resource_class_id(self) -> int | None:
        """Return the resource class id."""
        val = self.__get_annotation("renku.io/resource_class_id")
        try:
            return int(val) if val is not None else None
        except ValueError:
            return None

    @property
    def phase(self) -> str:
        """Return the phase, if it is an amalthea session the state."""
        if self.kind == "AmaltheaSession":
            return cast(str, self.pod.manifest.get("status", {}).get("state"))
        else:
            return cast(str, self.pod.manifest.get("status", {}).get("phase"))

    @property
    def resource_pool_id(self) -> int | None:
        """Return the resource pool id."""
        return None  # TODO implement when annotation is added

    @property
    def start_or_creation_time(self) -> datetime:
        """Return startTime or creationTime of the pod or pvc."""
        kind = self.kind
        dtstr: str
        if kind == "PersistentVolumeClaim" or kind == "AmaltheaSession":
            dtstr = self.pod.manifest.get("metadata", {}).get("creationTimestamp")
        elif kind == "Pod":
            dtstr = self.pod.manifest.get("status", {}).get("startTime")
        else:
            raise ValueError(f"No startTime/creationTime for kind {kind}")

        if dtstr is None:
            raise ValueError(f"No startTime/creationTime found on {kind} {self.uid}")
        else:
            # note: using this instead of datetime, because the k8s library uses this
            # but it doesn't expose the parsing itself
            return parse_datetime(dtstr)

    @property
    def namespace(self) -> str:
        """Return the namespace."""
        return cast(str, self.pod.manifest.metadata.namespace)

    @property
    def requested_data(self) -> RequestData:
        """Return the requested resources."""
        result = RequestData.empty().with_disk(self.status_storage)
        for container in self.pod.manifest.get("spec", {}).get("containers", []):
            requests = container.get("resources", {}).get("requests", {})
            lims = container.get("resources", {}).get("limits", {})

            cpu_req = ComputeCapacity.from_str(requests.get("cpu", ""))
            mem_req = DataSize.from_str(requests.get("memory", ""))
            gpu_req = ComputeCapacity.from_str(lims.get("nvidia.com/gpu") or requests.get("nvidia.com/gpu", ""))

            result = result + RequestData(cpu=cpu_req, memory=mem_req, gpu=gpu_req, disk=None)

        return result

    def to_resources_request(
        self, cluster_id: ClusterId | None, date: datetime, interval: timedelta
    ) -> ResourcesRequest:
        """Convert this into a ResourcesRequest data class."""
        return ResourcesRequest(
            namespace=self.namespace,
            name=self.name,
            uid=self.uid,
            kind=self.kind,
            api_version=self.api_version,
            phase=self.phase,
            capture_date=date,
            capture_interval=interval,
            cluster_id=cluster_id,
            user_id=self.user_id,
            project_id=self.project_id,
            launcher_id=self.launcher_id,
            resource_class_id=self.resource_class_id,
            resource_pool_id=self.resource_pool_id,
            since=self.start_or_creation_time,
            gpu_slice=None,  ## TODO get the cpu slice from somewhere
            data=self.requested_data,
        )


@dataclass(frozen=True)
class Credit:
    """A normalized number for counting usage and balances on resources."""

    value: int

    def __add__(self, other: Credit) -> Credit:
        return Credit(self.value + other.value)

    def __mult__(self, f: float) -> Credit:
        return Credit(round(self.value * f))

    def __str__(self) -> str:
        return str(self.value)

    @classmethod
    def from_int(cls, n: int) -> Credit:
        """Create new credit from the given number."""
        return Credit(value=n)


@dataclass
class ResourceUsage:
    """Capture resource usage."""

    cluster_id: ULID | None
    user_id: str
    resource_pool_id: int | None
    resource_class_id: int | None
    capture_date: date
    gpu_slice: float | None
    cpu_hours: float | None
    mem_hours: float | None
    disk_hours: float | None
    gpu_hours: float | None

    def to_credits(self, one_gpu: Credit | None = None) -> Credit:
        """Calculate the amount in credits."""
        cpu_credit = self.cpu_hours
        mem_credit = self.mem_hours / (1024 * 1024 * 1024) / 2 if self.mem_hours is not None else None
        disk_credit = self.disk_hours / (1024 * 1024 * 1024) / 20 if self.disk_hours is not None else None
        slice = self.gpu_slice or 0.2
        one = one_gpu or Credit.from_int(10)
        gpu_credits = self.gpu_hours * floor(one.value * (slice**0.6)) if self.gpu_hours is not None else None
        return Credit.from_int(round((cpu_credit or 0) + (mem_credit or 0) + (disk_credit or 0) + (gpu_credits or 0)))


@dataclass(frozen=True)
class ResourceUsageQuery:
    """Data for querying resource usage."""

    since: date
    until: date
    user_id: str | None = None
    resource_pool_id: int | None = None

    def with_user_id(self, id: str) -> ResourceUsageQuery:
        """Return a copy with the given user_id set."""
        return ResourceUsageQuery(self.since, self.until, id, self.resource_pool_id)

    def with_resource_pool_id(self, id: int) -> ResourceUsageQuery:
        """Return a copy with the given resource pool id set."""
        return ResourceUsageQuery(self.since, self.until, self.user_id, id)


@dataclass(frozen=True)
class ResourcePoolLimits:
    """Limits for a resource pool."""

    pool_id: int
    total_limit: Credit
    user_limit: Credit
