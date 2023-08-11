from dataclasses import dataclass
from typing import Optional, Callable, Dict, Any

from marshmallow import Schema, fields, post_load

from ...config import config
from .custom_fields import ByteSizeField, CpuField, GpuField


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

    def __post_init__(self):
        if self.default_url is None:
            self.default_url = config.server_options.defaults["defaultUrl"]
        if self.lfs_auto_fetch is None:
            self.lfs_auto_fetch = config.server_options.defaults["lfs_auto_fetch"]
        if self.storage is None and self.gigabytes:
            self.storage = 1
        elif self.storage is None and not self.gigabytes:
            self.storage = 1_000_000_000

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

    @classmethod
    def from_resource_class(cls, data: Dict[str, Any]) -> "ServerOptions":
        """Convert a CRC resource class to server options. CRC users GB for storage and memory
        whereas the notebook service uses bytes so we convert to bytes here."""
        return cls(
            cpu=data["cpu"],
            memory=data["memory"] * 1000000000,
            gpu=data["gpu"],
            storage=data["default_storage"] * 1000000000,
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
