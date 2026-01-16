"""Data model."""

from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from kubernetes.utils.quantity import parse_quantity


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
    data: RequestData

    @property
    def id(self) -> str:
        """Return an identifier string."""
        return f"{self.namespace}/{self.pod_name}@{self.capture_date}"

    def to_zero(self) -> ResourcesRequest:
        """Return a new value with all numbers set to 0."""
        return ResourcesRequest(
            namespace=self.namespace,
            pod_name=self.pod_name,
            capture_date=self.capture_date,
            data=RequestData.zero(),
        )

    def add(self, other: ResourcesRequest) -> ResourcesRequest:
        """Adds the values of other to this returning a new value. Returns this if both ids do not match."""
        if other.id == self.id:
            return ResourcesRequest(
                namespace=self.namespace,
                pod_name=self.pod_name,
                capture_date=self.capture_date,
                data=self.data + other.data,
            )
        else:
            return self

    def __str__(self) -> str:
        return f"{self.namespace}/{self.pod_name}: {self.data}  @ {self.capture_date}"

    @classmethod
    def zero(cls, namespace: str, pod_name: str, capture_date: datetime) -> ResourcesRequest:
        """Return a value with 0 only."""
        return ResourcesRequest(
            namespace=namespace, pod_name=pod_name, capture_date=capture_date, data=RequestData.zero()
        )
