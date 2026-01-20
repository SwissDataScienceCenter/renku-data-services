"""Data model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, cast

from kubernetes.utils.quantity import parse_quantity
from ulid import ULID

from renku_data_services.k8s.constants import ClusterId
from renku_data_services.k8s.models import K8sObject


@dataclass
class MemoryUsage:
    """memory usage data in bytes."""

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
    def from_string(cls, s: str) -> MemoryUsage | None:
        """Parse a quantity string."""
        try:
            return MemoryUsage(value=parse_quantity(s))
        except ValueError:
            return None

    @classmethod
    def zero(cls) -> MemoryUsage:
        """The zero value."""
        return MemoryUsage(value=Decimal(0))

    def __add__(self, other: Any) -> MemoryUsage:
        if isinstance(other, MemoryUsage):
            return MemoryUsage(self.value + other.value)
        else:
            raise Exception("")


@dataclass
class CpuUsage:
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
    def to_milli_cores(self) -> float:
        """Return the value in millicores."""
        return self.cores * (10**3)

    def __add__(self, other: Any) -> CpuUsage:
        if isinstance(other, CpuUsage):
            return CpuUsage(self.value + other.value)
        else:
            raise Exception(f"Cannot add value of type {type(other)} to CpuUsage")

    def __str__(self) -> str:
        return str(self.value)

    @classmethod
    def from_string(cls, s: str) -> CpuUsage | None:
        """Parses a quantity string."""
        try:
            return CpuUsage(value=parse_quantity(s))
        except ValueError:
            return None

    @classmethod
    def zero(cls) -> CpuUsage:
        """The zero value."""
        return CpuUsage(value=Decimal(0))


@dataclass
class RequestData:
    """Contains resource requests quantities."""

    cpu: CpuUsage
    gpu: CpuUsage
    memory: MemoryUsage

    def __str__(self) -> str:
        return f"cpu={self.cpu},mem={self.memory},gpu={self.gpu}"

    def __add__(self, other: Any) -> RequestData:
        if isinstance(other, RequestData):
            return RequestData(cpu=self.cpu + other.cpu, gpu=self.gpu + other.gpu, memory=self.memory + other.memory)
        else:
            raise Exception(f"Cannot add value of type {type(other)} to RequestData")

    @classmethod
    def zero(cls) -> RequestData:
        """Return a value with 0."""
        return RequestData(cpu=CpuUsage.zero(), gpu=CpuUsage.zero(), memory=MemoryUsage.zero())


@dataclass
class ResourcesRequest:
    """Data structure capturing request to resources."""

    namespace: str
    pod_name: str
    capture_date: datetime
    cluster_id: ClusterId | None
    user_id: str | None
    project_id: ULID | None
    launcher_id: ULID | None
    data: RequestData

    @property
    def id(self) -> str:
        """Return an identifier string."""
        cid = self.cluster_id or "default-cluster"
        return (
            f"{cid}/{self.namespace}/"
            f"{self.pod_name}/"
            f"{self.user_id}/"
            f"{self.project_id}/"
            f"{self.launcher_id}@{self.capture_date}"
        )

    def to_zero(self) -> ResourcesRequest:
        """Return a new value with all numbers set to 0."""
        return ResourcesRequest(
            namespace=self.namespace,
            pod_name=self.pod_name,
            capture_date=self.capture_date,
            cluster_id=self.cluster_id,
            user_id=self.user_id,
            project_id=self.project_id,
            launcher_id=self.launcher_id,
            data=RequestData.zero(),
        )

    def add(self, other: ResourcesRequest) -> ResourcesRequest:
        """Adds the values of other to this returning a new value. Returns this if both ids do not match."""
        if other.id == self.id:
            return ResourcesRequest(
                namespace=self.namespace,
                pod_name=self.pod_name,
                capture_date=self.capture_date,
                cluster_id=self.cluster_id,
                user_id=self.user_id or other.user_id,
                project_id=self.project_id or other.project_id,
                launcher_id=self.launcher_id or other.launcher_id,
                data=self.data + other.data,
            )
        else:
            return self

    def __str__(self) -> str:
        return (
            f"{self.cluster_id or "default-cluster"}/"
            f"{self.namespace}/"
            f"{self.pod_name}/{self.user_id}/{self.project_id}: {self.data}  @ {self.capture_date}"
        )


@dataclass
class ResourceDataFacade:
    """Wraps a k8s session or pod extracting certain data."""

    pod: K8sObject

    def __get_annotation(self, name: str) -> str | None:
        value = self.pod.manifest.get("metadata", {}).get("annotations", {}).get(name)
        return cast(str, value) if value else None

    def __get_label(self, name: str) -> str | None:
        value = self.pod.manifest.get("metadata", {}).get("labels", {}).get(name)
        return cast(str, value) if value else None

    @property
    def name(self) -> str:
        """Return the pod name."""
        return cast(str, self.pod.manifest.metadata.name)

    def get_k8s_name(self) -> str | None:
        """Return the kubernetes name."""
        return self.__get_label("app.kubernetes.io/name")

    @property
    def session_instance_id(self) -> str | None:
        """Get the session instance name if this is a pod started for a session."""
        k8s_name = self.__get_label("app.kubernetes.io/name")
        if k8s_name == "AmaltheaSession":
            return self.__get_label("app.kubernetes.io/instance")
        else:
            return None

    @property
    def user_id(self) -> str | None:
        """Return the user_id asscociated to this resource."""
        return self.__get_label("renku.io/safe-username")

    @property
    def project_id(self) -> ULID | None:
        """Return the project id if this is a pod associated to a session."""
        id = self.__get_annotation("renku.io/project_id")
        return ULID.from_str(id) if id else None

    @property
    def launcher_id(self) -> ULID | None:
        """Return the launcher id if this is a pod associated to a session."""
        id = self.__get_annotation("renku.io/launcher_id")
        return ULID.from_str(id) if id else None

    @property
    def namespace(self) -> str:
        """Return the namespace."""
        return cast(str, self.pod.manifest.metadata.namespace)

    @property
    def requested_data(self) -> RequestData:
        """Return the requested resources."""
        result = RequestData.zero()
        for container in self.pod.manifest.get("spec", {}).get("containers", []):
            requests = container.get("resources", {}).get("requests", {})
            lims = container.get("resources", {}).get("limits", {})

            cpu_req = CpuUsage.from_string(requests.get("cpu", "0"))
            mem_req = MemoryUsage.from_string(requests.get("memory", "0"))
            gpu_req = CpuUsage.from_string(lims.get("nvidia.com/gpu") or requests.get("nvidia.com/gpu", "0"))

            result = result + RequestData(
                cpu=cpu_req or CpuUsage.zero(),
                memory=mem_req or MemoryUsage.zero(),
                gpu=gpu_req or CpuUsage.zero(),
            )

        return result

    def to_resources_request(self, cluster_id: ClusterId | None, date: datetime) -> ResourcesRequest:
        """Convert this into a ResourcesRequest data class."""
        return ResourcesRequest(
            namespace=self.namespace,
            pod_name=self.name,
            capture_date=date,
            cluster_id=cluster_id,
            user_id=self.user_id,
            project_id=self.project_id,
            launcher_id=self.launcher_id,
            data=self.requested_data,
        )
