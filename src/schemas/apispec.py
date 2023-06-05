# generated by datamodel-codegen:
#   filename:  api.spec.yaml
#   timestamp: 2023-06-05T17:55:51+00:00

from __future__ import annotations

from typing import List, Optional

from pydantic import Extra, Field

from schemas.base import BaseAPISpec


class Version(BaseAPISpec):
    version: str


class IntegerIds(BaseAPISpec):
    __root__: List[int] = Field(..., example=[1, 3, 5], min_items=1, unique_items=True)


class Error(BaseAPISpec):
    code: int = Field(..., example=1404, gt=0)
    detail: Optional[str] = Field(None, example="A more detailed optional message showing what the problem was")
    message: str = Field(..., example="Something went wrong - please try again later")


class ErrorResponse(BaseAPISpec):
    error: Error


class ResourceClass(BaseAPISpec):
    class Config:
        extra = Extra.forbid

    name: str = Field(..., description="A name for a specific resource", example="the name of a resource", min_length=5)
    cpu: float = Field(..., description="Number of cpu cores", example=10, gt=0.0)
    memory: int = Field(..., description="Number of gigabytes of memory", example=4, gt=0)
    gpu: int = Field(..., description="Number of GPUs", example=8, ge=0)
    max_storage: int = Field(..., description="Number of gigabytes of storage", example=100, gt=0)
    default_storage: int = Field(..., description="Number of gigabytes of storage", example=100, gt=0)
    default: bool = Field(..., description="A default selection for resource classes or resource pools", example=False)


class ResourceClassPatch(BaseAPISpec):
    class Config:
        extra = Extra.forbid

    name: Optional[str] = Field(
        None, description="A name for a specific resource", example="the name of a resource", min_length=5
    )
    cpu: Optional[float] = Field(None, description="Number of cpu cores", example=10, gt=0.0)
    memory: Optional[int] = Field(None, description="Number of gigabytes of memory", example=4, gt=0)
    gpu: Optional[int] = Field(None, description="Number of GPUs", example=8, ge=0)
    max_storage: Optional[int] = Field(None, description="Number of gigabytes of storage", example=100, gt=0)
    default_storage: Optional[int] = Field(None, description="Number of gigabytes of storage", example=100, gt=0)
    default: Optional[bool] = Field(
        None, description="A default selection for resource classes or resource pools", example=False
    )


class ResourceClassPatchWithId(BaseAPISpec):
    class Config:
        extra = Extra.forbid

    name: Optional[str] = Field(
        None, description="A name for a specific resource", example="the name of a resource", min_length=5
    )
    cpu: Optional[float] = Field(None, description="Number of cpu cores", example=10, gt=0.0)
    memory: Optional[int] = Field(None, description="Number of gigabytes of memory", example=4, gt=0)
    gpu: Optional[int] = Field(None, description="Number of GPUs", example=8, ge=0)
    max_storage: Optional[int] = Field(None, description="Number of gigabytes of storage", example=100, gt=0)
    default_storage: Optional[int] = Field(None, description="Number of gigabytes of storage", example=100, gt=0)
    id: int = Field(..., description="An integer ID used to identify different resources", example=1, ge=0)
    default: Optional[bool] = Field(
        None, description="A default selection for resource classes or resource pools", example=False
    )


class ResourceClassWithId(BaseAPISpec):
    class Config:
        extra = Extra.forbid

    name: str = Field(..., description="A name for a specific resource", example="the name of a resource", min_length=5)
    cpu: float = Field(..., description="Number of cpu cores", example=10, gt=0.0)
    memory: int = Field(..., description="Number of gigabytes of memory", example=4, gt=0)
    gpu: int = Field(..., description="Number of GPUs", example=8, ge=0)
    max_storage: int = Field(..., description="Number of gigabytes of storage", example=100, gt=0)
    default_storage: int = Field(..., description="Number of gigabytes of storage", example=100, gt=0)
    id: int = Field(..., description="An integer ID used to identify different resources", example=1, ge=0)
    default: bool = Field(..., description="A default selection for resource classes or resource pools", example=False)


class ResourceClassesWithIdItem(ResourceClass):
    id: int = Field(..., description="An integer ID used to identify different resources", example=1, ge=0)


class UserWithId(BaseAPISpec):
    class Config:
        extra = Extra.forbid

    id: str = Field(
        ..., description="Keycloak user ID", example="123-keycloak-user-id-456", min_length=5, regex="^[A-Za-z0-9-]+$"
    )


class UsersWithId(BaseAPISpec):
    __root__: List[UserWithId] = Field(..., unique_items=True)


class Quota(BaseAPISpec):
    class Config:
        extra = Extra.forbid

    cpu: float = Field(..., description="Number of cpu cores", example=10, gt=0.0)
    memory: int = Field(..., description="Number of gigabytes of memory", example=4, gt=0)
    gpu: int = Field(..., description="Number of GPUs", example=8, ge=0)


class QuotaPatch(BaseAPISpec):
    class Config:
        extra = Extra.forbid

    cpu: Optional[float] = Field(None, description="Number of cpu cores", example=10, gt=0.0)
    memory: Optional[int] = Field(None, description="Number of gigabytes of memory", example=4, gt=0)
    gpu: Optional[int] = Field(None, description="Number of GPUs", example=8, ge=0)


class QuotaWithId(BaseAPISpec):
    class Config:
        extra = Extra.forbid

    cpu: float = Field(..., description="Number of cpu cores", example=10, gt=0.0)
    memory: int = Field(..., description="Number of gigabytes of memory", example=4, gt=0)
    gpu: int = Field(..., description="Number of GPUs", example=8, ge=0)
    id: str = Field(..., description="A name for a specific resource", example="the name of a resource", min_length=5)


class ResourcePool(BaseAPISpec):
    class Config:
        extra = Extra.forbid

    quota: Optional[Quota] = None
    classes: List[ResourceClass] = Field(..., min_items=1, unique_items=True)
    name: str = Field(..., description="A name for a specific resource", example="the name of a resource", min_length=5)
    public: bool = Field(..., description="A resource pool whose classes can be accessed by anyone", example=False)
    default: bool = Field(..., description="A default selection for resource classes or resource pools", example=False)


class ResourcePoolPatch(BaseAPISpec):
    class Config:
        extra = Extra.forbid

    quota: Optional[QuotaPatch] = None
    classes: Optional[List[ResourceClassPatchWithId]] = Field(
        None,
        example=[{"name": "resource class 1", "id": 1}, {"cpu": 4.5, "max_storage": 10000, "id": 2}],
        min_items=1,
        unique_items=True,
    )
    name: Optional[str] = Field(
        None, description="A name for a specific resource", example="the name of a resource", min_length=5
    )
    public: Optional[bool] = Field(
        None, description="A resource pool whose classes can be accessed by anyone", example=False
    )
    default: Optional[bool] = Field(
        None, description="A default selection for resource classes or resource pools", example=False
    )


class ResourcePoolPut(BaseAPISpec):
    class Config:
        extra = Extra.forbid

    quota: Optional[QuotaWithId] = None
    classes: List[ResourceClassesWithIdItem] = Field(
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
            },
            {
                "name": "resource class 2",
                "cpu": 4.5,
                "memory": 10,
                "gpu": 2,
                "max_storage": 10000,
                "id": 2,
                "default": False,
            },
        ],
        unique_items=True,
    )
    name: str = Field(..., description="A name for a specific resource", example="the name of a resource", min_length=5)
    public: bool = Field(..., description="A resource pool whose classes can be accessed by anyone", example=False)
    default: bool = Field(..., description="A default selection for resource classes or resource pools", example=False)


class ResourcePoolWithId(BaseAPISpec):
    class Config:
        extra = Extra.forbid

    quota: Optional[QuotaWithId] = None
    classes: List[ResourceClassWithId]
    name: str = Field(..., description="A name for a specific resource", example="the name of a resource", min_length=5)
    id: int = Field(..., description="An integer ID used to identify different resources", example=1, ge=0)
    public: bool = Field(..., description="A resource pool whose classes can be accessed by anyone", example=False)
    default: bool = Field(..., description="A default selection for resource classes or resource pools", example=False)


class ResourcePoolsWithId(BaseAPISpec):
    __root__: List[ResourcePoolWithId]
