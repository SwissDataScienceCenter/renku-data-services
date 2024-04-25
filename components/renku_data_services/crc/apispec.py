# generated by datamodel-codegen:
#   filename:  api.spec.yaml
#   timestamp: 2024-04-25T13:57:23+00:00

from __future__ import annotations

from typing import Any, List, Optional

from pydantic import ConfigDict, Field, RootModel
from renku_data_services.crc.apispec_base import BaseAPISpec


class UserPatch(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    no_default_access: Optional[bool] = Field(
        None,
        description="If set to true the user will not be able to use the default resource pool",
    )


class UserPut(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    no_default_access: bool = Field(
        ...,
        description="If set to true the user will not be able to use the default resource pool",
    )


class Version(BaseAPISpec):
    version: str


class IntegerIds(RootModel[List[int]]):
    root: List[int] = Field(..., example=[1, 3, 5], min_length=1)


class K8sLabel(RootModel[str]):
    root: str = Field(
        ...,
        description="A valid K8s label",
        example="some-label-1",
        max_length=63,
        min_length=3,
        pattern="^[a-z0-9A-Z][a-z0-9A-Z-_./]*[a-z0-9A-Z]$",
    )


class NodeAffinity(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str = Field(
        ...,
        description="A valid K8s label",
        example="some-label-1",
        max_length=63,
        min_length=3,
        pattern="^[a-z0-9A-Z][a-z0-9A-Z-_./]*[a-z0-9A-Z]$",
    )
    required_during_scheduling: bool = False


class Error(BaseAPISpec):
    code: int = Field(..., example=1404, gt=0)
    detail: Optional[str] = Field(
        None, example="A more detailed optional message showing what the problem was"
    )
    message: str = Field(..., example="Something went wrong - please try again later")


class ErrorResponse(BaseAPISpec):
    error: Error


class PoolUserWithId(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: str = Field(
        ...,
        description="Keycloak user ID",
        example="f74a228b-1790-4276-af5f-25c2424e9b0c",
    )
    no_default_access: bool = Field(
        False,
        description="If set to true the user will not be able to use the default resource pool",
    )


class PoolUsersWithId(RootModel[List[PoolUserWithId]]):
    root: List[PoolUserWithId]


class Quota(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    cpu: float = Field(..., description="Number of cpu cores", example=10, gt=0.0)
    memory: int = Field(
        ...,
        description="Number of gigabytes of memory",
        example=4,
        gt=0,
        le=9223372036854775807,
    )
    gpu: int = Field(
        ..., description="Number of GPUs", example=8, ge=0, le=9223372036854775807
    )


class QuotaPatch(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    cpu: Optional[float] = Field(
        None, description="Number of cpu cores", example=10, gt=0.0
    )
    memory: Optional[int] = Field(
        None,
        description="Number of gigabytes of memory",
        example=4,
        gt=0,
        le=9223372036854775807,
    )
    gpu: Optional[int] = Field(
        None, description="Number of GPUs", example=8, ge=0, le=9223372036854775807
    )


class QuotaWithId(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    cpu: float = Field(..., description="Number of cpu cores", example=10, gt=0.0)
    memory: int = Field(
        ...,
        description="Number of gigabytes of memory",
        example=4,
        gt=0,
        le=9223372036854775807,
    )
    gpu: int = Field(
        ..., description="Number of GPUs", example=8, ge=0, le=9223372036854775807
    )
    id: str = Field(
        ...,
        description="A name for a specific resource",
        example="the name of a resource",
        min_length=5,
    )


class ResourceClass(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: str = Field(
        ...,
        description="A name for a specific resource",
        example="the name of a resource",
        min_length=5,
    )
    cpu: float = Field(..., description="Number of cpu cores", example=10, gt=0.0)
    memory: int = Field(
        ...,
        description="Number of gigabytes of memory",
        example=4,
        gt=0,
        le=9223372036854775807,
    )
    gpu: int = Field(
        ..., description="Number of GPUs", example=8, ge=0, le=9223372036854775807
    )
    max_storage: int = Field(
        ...,
        description="Number of gigabytes of storage",
        example=100,
        gt=0,
        le=9223372036854775807,
    )
    default_storage: int = Field(
        ...,
        description="Number of gigabytes of storage",
        example=100,
        gt=0,
        le=9223372036854775807,
    )
    default: bool = Field(
        ...,
        description="A default selection for resource classes or resource pools",
        example=False,
    )
    tolerations: Optional[List[K8sLabel]] = Field(
        None,
        description="A list of k8s labels used for tolerations",
        example=["test-label-1"],
        min_length=0,
    )
    node_affinities: Optional[List[NodeAffinity]] = Field(
        None,
        description="A list of k8s labels used for tolerations and/or node affinity",
        example=[{"key": "test-label-1", "required_during_scheduling": False}],
        min_length=0,
    )


class ResourceClassPatch(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: Optional[str] = Field(
        None,
        description="A name for a specific resource",
        example="the name of a resource",
        min_length=5,
    )
    cpu: Optional[float] = Field(
        None, description="Number of cpu cores", example=10, gt=0.0
    )
    memory: Optional[int] = Field(
        None,
        description="Number of gigabytes of memory",
        example=4,
        gt=0,
        le=9223372036854775807,
    )
    gpu: Optional[int] = Field(
        None, description="Number of GPUs", example=8, ge=0, le=9223372036854775807
    )
    max_storage: Optional[int] = Field(
        None,
        description="Number of gigabytes of storage",
        example=100,
        gt=0,
        le=9223372036854775807,
    )
    default_storage: Optional[int] = Field(
        None,
        description="Number of gigabytes of storage",
        example=100,
        gt=0,
        le=9223372036854775807,
    )
    default: Optional[bool] = Field(
        None,
        description="A default selection for resource classes or resource pools",
        example=False,
    )
    tolerations: Optional[List[K8sLabel]] = Field(
        None,
        description="A list of k8s labels used for tolerations",
        example=["test-label-1"],
        min_length=0,
    )
    node_affinities: Optional[List[NodeAffinity]] = Field(
        None,
        description="A list of k8s labels used for tolerations and/or node affinity",
        example=[{"key": "test-label-1", "required_during_scheduling": False}],
        min_length=0,
    )


class ResourceClassPatchWithId(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: Optional[str] = Field(
        None,
        description="A name for a specific resource",
        example="the name of a resource",
        min_length=5,
    )
    cpu: Optional[float] = Field(
        None, description="Number of cpu cores", example=10, gt=0.0
    )
    memory: Optional[int] = Field(
        None,
        description="Number of gigabytes of memory",
        example=4,
        gt=0,
        le=9223372036854775807,
    )
    gpu: Optional[int] = Field(
        None, description="Number of GPUs", example=8, ge=0, le=9223372036854775807
    )
    max_storage: Optional[int] = Field(
        None,
        description="Number of gigabytes of storage",
        example=100,
        gt=0,
        le=9223372036854775807,
    )
    default_storage: Optional[int] = Field(
        None,
        description="Number of gigabytes of storage",
        example=100,
        gt=0,
        le=9223372036854775807,
    )
    id: int = Field(
        ...,
        description="An integer ID used to identify different resources",
        example=1,
        ge=0,
    )
    default: Optional[bool] = Field(
        None,
        description="A default selection for resource classes or resource pools",
        example=False,
    )
    tolerations: Optional[List[K8sLabel]] = Field(
        None,
        description="A list of k8s labels used for tolerations",
        example=["test-label-1"],
        min_length=0,
    )
    node_affinities: Optional[List[NodeAffinity]] = Field(
        None,
        description="A list of k8s labels used for tolerations and/or node affinity",
        example=[{"key": "test-label-1", "required_during_scheduling": False}],
        min_length=0,
    )


class ResourceClassWithId(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: str = Field(
        ...,
        description="A name for a specific resource",
        example="the name of a resource",
        min_length=5,
    )
    cpu: float = Field(..., description="Number of cpu cores", example=10, gt=0.0)
    memory: int = Field(
        ...,
        description="Number of gigabytes of memory",
        example=4,
        gt=0,
        le=9223372036854775807,
    )
    gpu: int = Field(
        ..., description="Number of GPUs", example=8, ge=0, le=9223372036854775807
    )
    max_storage: int = Field(
        ...,
        description="Number of gigabytes of storage",
        example=100,
        gt=0,
        le=9223372036854775807,
    )
    default_storage: int = Field(
        ...,
        description="Number of gigabytes of storage",
        example=100,
        gt=0,
        le=9223372036854775807,
    )
    id: int = Field(
        ...,
        description="An integer ID used to identify different resources",
        example=1,
        ge=0,
    )
    default: bool = Field(
        ...,
        description="A default selection for resource classes or resource pools",
        example=False,
    )
    tolerations: Optional[List[K8sLabel]] = Field(
        None,
        description="A list of k8s labels used for tolerations",
        example=["test-label-1"],
        min_length=0,
    )
    node_affinities: Optional[List[NodeAffinity]] = Field(
        None,
        description="A list of k8s labels used for tolerations and/or node affinity",
        example=[{"key": "test-label-1", "required_during_scheduling": False}],
        min_length=0,
    )


class ResourceClassWithIdFiltered(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: str = Field(
        ...,
        description="A name for a specific resource",
        example="the name of a resource",
        min_length=5,
    )
    cpu: float = Field(..., description="Number of cpu cores", example=10, gt=0.0)
    memory: int = Field(
        ...,
        description="Number of gigabytes of memory",
        example=4,
        gt=0,
        le=9223372036854775807,
    )
    gpu: int = Field(
        ..., description="Number of GPUs", example=8, ge=0, le=9223372036854775807
    )
    max_storage: int = Field(
        ...,
        description="Number of gigabytes of storage",
        example=100,
        gt=0,
        le=9223372036854775807,
    )
    default_storage: int = Field(
        ...,
        description="Number of gigabytes of storage",
        example=100,
        gt=0,
        le=9223372036854775807,
    )
    id: int = Field(
        ...,
        description="An integer ID used to identify different resources",
        example=1,
        ge=0,
    )
    default: bool = Field(
        ...,
        description="A default selection for resource classes or resource pools",
        example=False,
    )
    matching: Optional[bool] = None
    tolerations: Optional[List[K8sLabel]] = Field(
        None,
        description="A list of k8s labels used for tolerations",
        example=["test-label-1"],
        min_length=0,
    )
    node_affinities: Optional[List[NodeAffinity]] = Field(
        None,
        description="A list of k8s labels used for tolerations and/or node affinity",
        example=[{"key": "test-label-1", "required_during_scheduling": False}],
        min_length=0,
    )


class ResourcePool(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    quota: Optional[Quota] = None
    classes: List[ResourceClass] = Field(..., min_length=1)
    name: str = Field(
        ...,
        description="A name for a specific resource",
        example="the name of a resource",
        min_length=5,
    )
    public: bool = Field(
        ...,
        description="A resource pool whose classes can be accessed by anyone",
        example=False,
    )
    default: bool = Field(
        ...,
        description="A default selection for resource classes or resource pools",
        example=False,
    )
    idle_threshold: Optional[Any] = Field(
        None,
        description="A threshold in seconds after which a session gets hibernated",
        ge=1,
    )
    hibernation_threshold: Optional[Any] = Field(
        None,
        description="A threshold in seconds after which a session gets culled/deleted",
        ge=1,
    )


class ResourcePoolPatch(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    quota: Optional[QuotaPatch] = None
    classes: Optional[List[ResourceClassPatchWithId]] = Field(
        None,
        example=[
            {"name": "resource class 1", "id": 1},
            {"cpu": 4.5, "max_storage": 10000, "id": 2},
        ],
        min_length=1,
    )
    name: Optional[str] = Field(
        None,
        description="A name for a specific resource",
        example="the name of a resource",
        min_length=5,
    )
    public: Optional[bool] = Field(
        None,
        description="A resource pool whose classes can be accessed by anyone",
        example=False,
    )
    default: Optional[bool] = Field(
        None,
        description="A default selection for resource classes or resource pools",
        example=False,
    )
    idle_threshold: Optional[Any] = Field(
        None,
        description="A threshold in seconds after which a session gets hibernated",
        ge=1,
    )
    hibernation_threshold: Optional[Any] = Field(
        None,
        description="A threshold in seconds after which a session gets culled/deleted",
        ge=1,
    )


class ResourcePoolPut(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    quota: Optional[QuotaWithId] = None
    classes: List[ResourceClassWithId] = Field(
        ...,
        example=[
            {
                "name": "resource class 1",
                "cpu": 1.5,
                "memory": 2,
                "gpu": 0,
                "max_storage": 100,
                "id": 1,
                "default": True,
                "default_storage": 10,
            },
            {
                "name": "resource class 2",
                "cpu": 4.5,
                "memory": 10,
                "gpu": 2,
                "default_storage": 10,
                "max_storage": 10000,
                "id": 2,
                "default": False,
            },
        ],
    )
    name: str = Field(
        ...,
        description="A name for a specific resource",
        example="the name of a resource",
        min_length=5,
    )
    public: bool = Field(
        ...,
        description="A resource pool whose classes can be accessed by anyone",
        example=False,
    )
    default: bool = Field(
        ...,
        description="A default selection for resource classes or resource pools",
        example=False,
    )
    idle_threshold: Optional[Any] = Field(
        None,
        description="A threshold in seconds after which a session gets hibernated",
        ge=1,
    )
    hibernation_threshold: Optional[Any] = Field(
        None,
        description="A threshold in seconds after which a session gets culled/deleted",
        ge=1,
    )


class ResourcePoolWithId(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    quota: Optional[QuotaWithId] = None
    classes: List[ResourceClassWithId]
    name: str = Field(
        ...,
        description="A name for a specific resource",
        example="the name of a resource",
        min_length=5,
    )
    id: int = Field(
        ...,
        description="An integer ID used to identify different resources",
        example=1,
        ge=0,
    )
    public: bool = Field(
        ...,
        description="A resource pool whose classes can be accessed by anyone",
        example=False,
    )
    default: bool = Field(
        ...,
        description="A default selection for resource classes or resource pools",
        example=False,
    )
    idle_threshold: Optional[Any] = Field(
        None,
        description="A threshold in seconds after which a session gets hibernated",
        ge=1,
    )
    hibernation_threshold: Optional[Any] = Field(
        None,
        description="A threshold in seconds after which a session gets culled/deleted",
        ge=1,
    )


class ResourcePoolWithIdFiltered(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    quota: Optional[QuotaWithId] = None
    classes: List[ResourceClassWithIdFiltered]
    name: str = Field(
        ...,
        description="A name for a specific resource",
        example="the name of a resource",
        min_length=5,
    )
    id: int = Field(
        ...,
        description="An integer ID used to identify different resources",
        example=1,
        ge=0,
    )
    public: bool = Field(
        ...,
        description="A resource pool whose classes can be accessed by anyone",
        example=False,
    )
    default: bool = Field(
        ...,
        description="A default selection for resource classes or resource pools",
        example=False,
    )
    idle_threshold: Optional[Any] = Field(
        None,
        description="A threshold in seconds after which a session gets hibernated",
        ge=1,
    )
    hibernation_threshold: Optional[Any] = Field(
        None,
        description="A threshold in seconds after which a session gets culled/deleted",
        ge=1,
    )


class ResourcePoolsWithId(RootModel[List[ResourcePoolWithId]]):
    root: List[ResourcePoolWithId]


class ResourcePoolsWithIdFiltered(RootModel[List[ResourcePoolWithIdFiltered]]):
    root: List[ResourcePoolWithIdFiltered]
