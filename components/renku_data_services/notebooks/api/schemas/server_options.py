from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from marshmallow import Schema, fields, post_load

from ...config import config
from ...config.dynamic import CPUEnforcement
from .custom_fields import ByteSizeField, CpuField, GpuField
from ...errors.programming import ProgrammingError


@dataclass
class NodeAffinity:
    """Node affinity used to schedule a session on specific nodes."""

    key: str
    required_during_scheduling: bool = False

    def json_match_expression(self) -> Dict[str, str]:
        return {
            "key": self.key,
            "operator": "Exists",
        }


@dataclass
class Toleration:
    """Toleration used to schedule a session on tainted nodes."""

    key: str

    def json_match_expression(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "operator": "Exists",
        }


@dataclass
class ServerOptions:
    """Server options. Memory and storage are in bytes."""

    cpu: float
    memory: int
    gpu: int
    storage: Optional[int] = None
    default_url: Optional[str] = None
    lfs_auto_fetch: bool = False
    gigabytes: bool = False
    priority_class: Optional[str] = None
    node_affinities: List[NodeAffinity] = field(default_factory=list)
    tolerations: List[Toleration] = field(default_factory=list)
    resource_class_id: Optional[int] = None

    def __post_init__(self):
        if self.default_url is None:
            self.default_url = config.server_options.defaults["defaultUrl"]
        if self.lfs_auto_fetch is None:
            self.lfs_auto_fetch = config.server_options.defaults["lfs_auto_fetch"]
        if self.storage is None and self.gigabytes:
            self.storage = 1
        elif self.storage is None and not self.gigabytes:
            self.storage = 1_000_000_000
        if not all([isinstance(i, NodeAffinity) for i in self.node_affinities]):
            raise ProgrammingError(
                message="Cannot create a ServerOptions dataclass with node "
                "affinities that are not of type NodeAffinity"
            )
        if not all([isinstance(i, Toleration) for i in self.tolerations]):
            raise ProgrammingError(
                message="Cannot create a ServerOptions dataclass with tolerations "
                "that are not of type Toleration"
            )
        if self.node_affinities is None:
            self.node_affinities = []
        else:
            self.node_affinities = sorted(
                self.node_affinities,
                key=lambda x: (x.key, x.required_during_scheduling),
            )
        if self.tolerations is None:
            self.tolerations = []
        else:
            self.tolerations = sorted(self.tolerations, key=lambda x: x.key)

    def __compare(
        self,
        other: "ServerOptions",
        compare_func: Callable[["ServerOptions", "ServerOptions"], bool],
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

    def set_storage(self, storage: int, gigabytes: bool = False):
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

    def __ge__(self, other: "ServerOptions"):
        return self.__compare(other, lambda x, y: x >= y)

    def __gt__(self, other: "ServerOptions"):
        return self.__compare(other, lambda x, y: x > y)

    def __lt__(self, other: "ServerOptions"):
        return self.__compare(other, lambda x, y: x < y)

    def __le__(self, other: "ServerOptions"):
        return self.__compare(other, lambda x, y: x <= y)

    def __eq__(self, other: "ServerOptions"):
        numeric_value_equal = self.__compare(other, lambda x, y: x == y)
        return (
            numeric_value_equal
            and self.default_url == other.default_url
            and self.lfs_auto_fetch == other.lfs_auto_fetch
            and self.gigabytes == other.gigabytes
            and self.priority_class == other.priority_class
        )

    def to_k8s_resources(
        self, enforce_cpu_limits: CPUEnforcement = CPUEnforcement.OFF
    ) -> Dict[str, Any]:
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
    def from_resource_class(cls, data: Dict[str, Any]) -> "ServerOptions":
        """Convert a CRC resource class to server options. CRC users GB for storage and memory
        whereas the notebook service uses bytes so we convert to bytes here."""
        return cls(
            cpu=data["cpu"],
            memory=data["memory"] * 1000000000,
            gpu=data["gpu"],
            storage=data["default_storage"] * 1000000000,
            node_affinities=[NodeAffinity(**a) for a in data.get("node_affinities", [])],
            tolerations=[Toleration(t) for t in data.get("tolerations", [])],
            resource_class_id=data.get("id"),
        )

    @classmethod
    def from_request(cls, data: Dict[str, Any]) -> "ServerOptions":
        """Convert a server options request dictionary to the model."""
        return ServerOptions(
            cpu=data["cpu_request"],
            gpu=data["gpu_request"],
            memory=data["mem_request"],
            default_url=data["defaultUrl"],
            lfs_auto_fetch=data["lfs_auto_fetch"],
            storage=data["disk_request"],
        )


class LaunchNotebookRequestServerOptions(Schema):
    """This is the old-style API server options and are only used to find suitable
    # resource class form the crc service. "Suitable" in this case is any resource
    # class where all its parameters are greather than or equal to the request. So
    # by assigning a value of 0 to a server option we are ensuring that CRC will
    # be able to easily find a match."""

    defaultUrl = fields.Str(
        required=False,
        load_default=config.server_options.defaults["defaultUrl"],
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
        load_default=config.server_options.defaults["lfs_auto_fetch"],
    )
    gpu_request = GpuField(
        required=False,
        load_default=0,
    )

    @post_load
    def make_dataclass(slef, data, **kwargs):
        return ServerOptions.from_request(data)
