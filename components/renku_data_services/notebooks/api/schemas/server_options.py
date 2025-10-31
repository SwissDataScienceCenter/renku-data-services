"""Options for a user session."""

from collections.abc import Callable
from dataclasses import dataclass, field
from operator import attrgetter
from typing import Any, Optional, Self

from marshmallow import Schema, fields

from renku_data_services.crc.models import ResourceClass
from renku_data_services.k8s.pod_scheduling import models as k8s_models
from renku_data_services.notebooks.api.schemas.custom_fields import ByteSizeField, CpuField, GpuField
from renku_data_services.notebooks.config.dynamic import CPUEnforcement
from renku_data_services.notebooks.errors.programming import ProgrammingError


@dataclass
class NodeAffinity:
    """Node affinity used to schedule a session on specific nodes."""

    key: str
    required_during_scheduling: bool = False

    def json_match_expression(self) -> dict[str, str]:
        """Create match expression for this class."""
        return {
            "key": self.key,
            "operator": "Exists",
        }


# @dataclass
# class Toleration:
#     """Toleration used to schedule a session on tainted nodes."""

#     key: str

#     def json_match_expression(self) -> dict[str, Any]:
#         """Create match expression for this class."""
#         return {
#             "key": self.key,
#             "operator": "Exists",
#         }


@dataclass
class ServerOptions:
    """Server options. Memory and storage are in bytes."""

    cpu: float
    memory: int | float
    gpu: int
    storage: Optional[int | float] = None
    default_url: str = "/lab"
    lfs_auto_fetch: bool = False
    gigabytes: bool = False
    priority_class: Optional[str] = None
    node_affinities: list[NodeAffinity] = field(default_factory=list)
    tolerations: list[k8s_models.Toleration] = field(default_factory=list)
    resource_class_id: Optional[int] = None
    idle_threshold_seconds: Optional[int] = None
    hibernation_threshold_seconds: Optional[int] = None

    def __post_init__(self) -> None:
        if self.storage is None and self.gigabytes:
            self.storage = 1
        elif self.storage is None and not self.gigabytes:
            self.storage = 1_000_000_000
        if not all([isinstance(affinity, NodeAffinity) for affinity in self.node_affinities]):
            raise ProgrammingError(
                message="Cannot create a ServerOptions dataclass with node "
                "affinities that are not of type NodeAffinity"
            )
        if not all([isinstance(toleration, k8s_models.Toleration) for toleration in self.tolerations]):
            raise ProgrammingError(
                message="Cannot create a ServerOptions dataclass with tolerations that are not of type Toleration"
            )
        if not self.node_affinities:
            self.node_affinities = []
        else:
            self.node_affinities = sorted(
                self.node_affinities,
                key=lambda x: (x.key, x.required_during_scheduling),
            )
        if not self.tolerations:
            self.tolerations = []
        else:
            self.tolerations = sorted(self.tolerations, key=attrgetter("key", "operator", "effect", "value"))
            # self.tolerations = sorted(self.tolerations, key=lambda x: x.key)

    def __compare(
        self,
        other: "ServerOptions",
        compare_func: Callable[[int | float, int | float], bool],
    ) -> bool:
        results = [
            compare_func(self.cpu, other.cpu),
            compare_func(self.memory, other.memory),
            compare_func(self.gpu, other.gpu),
        ]
        self_storage = 0 if self.storage is None else self.storage
        other_storage = 0 if other.storage is None else other.storage
        results.append(compare_func(self_storage, other_storage))
        return all(results)

    def to_gigabytes(self) -> "ServerOptions":
        """Get this oblects with all relevant sizes in gigabytes."""
        if self.gigabytes:
            return self
        return ServerOptions(
            cpu=self.cpu,
            gpu=self.gpu,
            default_url=self.default_url,
            lfs_auto_fetch=self.lfs_auto_fetch,
            memory=self.memory / 1000000000,
            storage=self.storage / 1000000000 if self.storage is not None else None,
            gigabytes=True,
        )

    def set_storage(self, storage: int, gigabytes: bool = False) -> None:
        """Set storage request for a session."""
        if self.gigabytes and not gigabytes:
            self.storage = round(storage / 1_000_000_000)
        elif not self.gigabytes and gigabytes:
            self.storage = round(storage * 1_000_000_000)
        else:
            self.storage = storage

    def __sub__(self, other: "ServerOptions") -> "ServerOptions":
        self_storage = 0 if self.storage is None else self.storage
        other_storage = 0 if other.storage is None else other.storage
        return ServerOptions(
            cpu=self.cpu - other.cpu,
            memory=self.memory - other.memory,
            gpu=self.gpu - other.gpu,
            storage=self_storage - other_storage,
        )

    def __ge__(self, other: "ServerOptions") -> bool:
        return self.__compare(other, lambda x, y: x >= y)

    def __gt__(self, other: "ServerOptions") -> bool:
        return self.__compare(other, lambda x, y: x > y)

    def __lt__(self, other: "ServerOptions") -> bool:
        return self.__compare(other, lambda x, y: x < y)

    def __le__(self, other: "ServerOptions") -> bool:
        return self.__compare(other, lambda x, y: x <= y)

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, type(self)):
            return False
        numeric_value_equal = self.__compare(other, lambda x, y: x == y)
        return (
            numeric_value_equal
            and self.default_url == other.default_url
            and self.lfs_auto_fetch == other.lfs_auto_fetch
            and self.gigabytes == other.gigabytes
            and self.priority_class == other.priority_class
        )

    def to_k8s_resources(self, enforce_cpu_limits: CPUEnforcement = CPUEnforcement.OFF) -> dict[str, Any]:
        """Convert to the K8s resource requests and limits for cpu, memory and gpus."""
        cpu_request = float(self.cpu)
        mem = f"{self.memory}G" if self.gigabytes else self.memory
        gpu_req = self.gpu
        gpu = {"nvidia.com/gpu": str(gpu_req)} if gpu_req > 0 else None
        resources = {
            "requests": {"memory": mem, "cpu": cpu_request},
            "limits": {"memory": mem},
        }
        if enforce_cpu_limits == CPUEnforcement.LAX:
            resources["limits"]["cpu"] = 3 * cpu_request
        elif enforce_cpu_limits == CPUEnforcement.STRICT:
            resources["limits"]["cpu"] = cpu_request
        if gpu:
            resources["requests"] = {**resources["requests"], **gpu}
            resources["limits"] = {**resources["limits"], **gpu}
        return resources

    @classmethod
    def from_resource_class(cls, data: ResourceClass) -> Self:
        """Convert a CRC resource class to server options.

        Data Service uses GB for storage and memory whereas the notebook service uses bytes so we convert to bytes here.
        """
        return cls(
            cpu=data.cpu,
            memory=data.memory * 1_000_000_000,
            gpu=data.gpu,
            storage=data.default_storage * 1_000_000_000,
            node_affinities=[
                NodeAffinity(key=a.key, required_during_scheduling=a.required_during_scheduling)
                for a in data.node_affinities
            ],
            # tolerations=[Toleration(t) for t in data.tolerations],
            tolerations=data.tolerations,
            resource_class_id=data.id,
        )

    @classmethod
    def from_request(cls, data: dict[str, Any]) -> Self:
        """Convert a server options request dictionary to the model."""
        return cls(
            cpu=data["cpu_request"],
            gpu=data["gpu_request"],
            memory=data["mem_request"],
            default_url=data["defaultUrl"],
            lfs_auto_fetch=data["lfs_auto_fetch"],
            storage=data["disk_request"],
        )

    @classmethod
    def from_server_options_request_schema(
        cls, data: dict[str, str | int | float | None], default_url_default: str, lfs_auto_fetch_default: bool
    ) -> Self:
        """Convert to dataclass from the result of the serialization from LaunchNotebookRequestServerOptions."""
        if data.get("defaultUrl") is None:
            data["defaultUrl"] = default_url_default
        if data.get("lfs_auto_fetch") is None:
            data["lfs_auto_fetch"] = lfs_auto_fetch_default
        return cls.from_request(data)


class LaunchNotebookRequestServerOptions(Schema):
    """This is the old-style API for server options.

    This is only used to find suitable resource class form the crc service. "Suitable" in this case is any resource
    class where all its parameters are greather than or equal to the request. So by assigning a value of 0 to a server
    option we are ensuring that CRC will be able to easily find a match.
    """

    defaultUrl = fields.Str(
        required=False,
    )
    cpu_request = CpuField(
        required=False,
        load_default=0,
    )
    mem_request = ByteSizeField(
        required=False,
        load_default=0,
    )
    disk_request = ByteSizeField(
        required=False,
        load_default=1_000_000_000,
    )
    lfs_auto_fetch = fields.Bool(
        required=False,
    )
    gpu_request = GpuField(
        required=False,
        load_default=0,
    )
