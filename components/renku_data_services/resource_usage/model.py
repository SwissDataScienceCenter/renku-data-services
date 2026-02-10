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
class ResourceDataFacade:
    """Wraps a k8s session, pod, node or pvc extracting certain data that should for being stored."""

    obj: K8sObject

    def __get_annotation(self, name: str) -> str | None:
        value = self.obj.manifest.get("metadata", {}).get("annotations", {}).get(name)
        return cast(str, value) if value is not None else None

    def __get_label(self, name: str) -> str | None:
        value = self.obj.manifest.get("metadata", {}).get("labels", {}).get(name)
        return cast(str, value) if value is not None else None

    @property
    def kind(self) -> str:
        """Return the kind."""
        return cast(str, self.obj.manifest.kind)

    @property
    def api_version(self) -> str:
        """Return the apiVersion field."""
        return cast(str, self.obj.manifest.get("apiVersion"))

    @property
    def resource_request_storage(self) -> DataSize | None:
        """Return the storage spec of a pvc."""
        value = self.obj.manifest.get("spec", {}).get("resources", {}).get("requests", {}).get("storage")
        return DataSize.from_str(str(value)) if value is not None else None

    @property
    def status_storage(self) -> DataSize | None:
        """Return the storage spec of a pvc."""
        value = self.obj.manifest.get("status", {}).get("capacity", {}).get("storage")
        return DataSize.from_str(str(value)) if value is not None else None

    @property
    def name(self) -> str:
        """Return the pod name."""
        return cast(str, self.obj.manifest.metadata.name)

    @property
    def node_name(self) -> str | None:
        """Return the node this pod is running on."""
        value = self.obj.manifest.get("spec", {}).get("nodeName")
        return str(value) if value is not None else None

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
        return cast(str, self.obj.manifest.metadata.uid)

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
            return cast(str, self.obj.manifest.get("status", {}).get("state"))
        else:
            return cast(str, self.obj.manifest.get("status", {}).get("phase"))

    @property
    def resource_pool_id(self) -> int | None:
        """Return the resource pool id."""
        val = self.__get_annotation("renku.io/resource_pool_id")
        try:
            return int(val) if val is not None else None
        except ValueError:
            return None

    @property
    def start_or_creation_time(self) -> datetime:
        """Return startTime or creationTime of the pod or pvc."""
        kind = self.kind
        dtstr: str
        if kind == "PersistentVolumeClaim" or kind == "AmaltheaSession":
            dtstr = self.obj.manifest.get("metadata", {}).get("creationTimestamp")
        elif kind == "Pod":
            dtstr = self.obj.manifest.get("status", {}).get("startTime")
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
        return cast(str, self.obj.manifest.metadata.namespace)

    @property
    def gpu_product(self) -> str | None:
        """Return the gpu product available on a node."""
        value = self.obj.manifest.get("metadata", {}).get("labels", {}).get("nvidia.com/gpu.product")
        return str(value) if value is not None else None

    @property
    def gpu_count(self) -> int | None:
        """Return the gpu count label available on a node."""
        value = self.obj.manifest.get("metadata", {}).get("labels", {}).get("nvidia.com/gpu.count")
        try:
            return int(value) if value is not None else None
        except ValueError:
            return None

    @property
    def requested_data(self) -> RequestData:
        """Return the requested resources."""
        result = RequestData.empty().with_disk(self.status_storage)
        for container in self.obj.manifest.get("spec", {}).get("containers", []):
            requests = container.get("resources", {}).get("requests", {})
            lims = container.get("resources", {}).get("limits", {})

            cpu_req = ComputeCapacity.from_str(requests.get("cpu", ""))
            mem_req = DataSize.from_str(requests.get("memory", ""))
            gpu_req = ComputeCapacity.from_str(lims.get("nvidia.com/gpu") or requests.get("nvidia.com/gpu", ""))

            result = result + RequestData(cpu=cpu_req, memory=mem_req, gpu=gpu_req, disk=None)

        return result


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

    @classmethod
    def from_hours(cls, hours: float) -> Credit:
        """Create a new credit converting runtime in hours."""
        return Credit(value=round(hours))

    @classmethod
    def from_seconds(cls, seconds: float) -> Credit:
        """Create a new credit converting runtime in seconds."""
        return cls.from_hours(seconds / 3600)


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


@dataclass(frozen=True)
class ResourceClassCost:
    """The costs associated to a resource class."""

    resource_class_id: int
    cost: Credit

    @classmethod
    def zero(cls, resource_class_id: int) -> ResourceClassCost:
        """Create an instance with a cost of 0."""
        return ResourceClassCost(resource_class_id=resource_class_id, cost=Credit.from_int(0))


@dataclass(frozen=True)
class ResourceClassRuntimeCost:
    """The costs and running time associated to a resource class."""

    resource_class_id: int
    runtime: timedelta
    user_id: str
    cost: Credit

    def to_effective_costs(self) -> float:
        """Calculate the effective costs for this runtime of the resource_class."""
        ## impl note: here we have the costs associated to the
        ## resource class and assume to be the cost for 1 hour for
        ## runtime
        hours = self.runtime.total_seconds() / 3600
        return hours * self.cost.value


@dataclass
class ResourceClassCostQuery:
    """Query for getting resource class costs."""

    since: date
    until: date
    resource_class_id: int
    user_id: str | None


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
    gpu_product: str | None
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
            f"{self.gpu_product}/"
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
            gpu_product=self.gpu_product,
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
                gpu_product=self.gpu_product,
                data=self.data + other.data,
            )
        else:
            return self

    def __str__(self) -> str:
        return f"{self.id}: {self.data}"

    @classmethod
    def from_pvc(
        cls,
        obj: ResourceDataFacade,
        cluster: ClusterId,
        date: datetime,
        interval: timedelta,
    ) -> ResourcesRequest:
        """Convert this into a ResourcesRequest data class."""
        return ResourcesRequest(
            namespace=obj.namespace,
            name=obj.name,
            uid=obj.uid,
            kind=obj.kind,
            api_version=obj.api_version,
            phase=obj.phase,
            capture_date=date,
            capture_interval=interval,
            cluster_id=cluster,
            user_id=obj.user_id,
            project_id=obj.project_id,
            launcher_id=obj.launcher_id,
            resource_class_id=obj.resource_class_id,
            resource_pool_id=obj.resource_pool_id,
            since=obj.start_or_creation_time,
            gpu_slice=None,
            gpu_product=None,
            data=obj.requested_data,
        )

    @classmethod
    def from_pod_and_node(
        cls,
        pod: ResourceDataFacade,
        node: ResourceDataFacade | None,
        cluster: ClusterId,
        date: datetime,
        interval: timedelta,
    ) -> ResourcesRequest:
        """Convert this into a ResourcesRequest data class."""
        gpu_slice: float | None = None
        if pod.requested_data.gpu is not None and node and node.gpu_count is not None:
            gpu_slice = pod.requested_data.gpu.cores / node.gpu_count
        gpu_product: str | None = None
        if node:
            gpu_product = node.gpu_product

        return ResourcesRequest(
            namespace=pod.namespace,
            name=pod.name,
            uid=pod.uid,
            kind=pod.kind,
            api_version=pod.api_version,
            phase=pod.phase,
            capture_date=date,
            capture_interval=interval,
            cluster_id=cluster,
            user_id=pod.user_id,
            project_id=pod.project_id,
            launcher_id=pod.launcher_id,
            resource_class_id=pod.resource_class_id,
            resource_pool_id=pod.resource_pool_id,
            since=pod.start_or_creation_time,
            gpu_slice=gpu_slice,
            gpu_product=gpu_product,
            data=pod.requested_data,
        )
