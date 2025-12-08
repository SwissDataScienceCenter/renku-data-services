"""Validation and parsing for the notebook service (old) style of server options and defaults.

The purpose of this is to be able to create resource
pools and classes based on the old server options until the admin UI interface
is added.
"""

from collections.abc import Generator
from typing import Any, Union

from pydantic import BaseModel, ByteSize, Field, validator

from renku_data_services.crc import models
from renku_data_services.crc.constants import DEFAULT_RUNTIME_PLATFORM


def _check_greater_than_zero(cls: Any, v: int | float) -> int | float:
    if v <= 0:
        raise ValueError(f"The provided value should be greater than zero, instead it was {v}.")
    return v


class ServerOptionsDefaults(BaseModel):
    """Used to parse the server option defaults passed to the notebook service in the Helm values."""

    cpu_request: float = Field(gt=0)
    mem_request: ByteSize
    disk_request: ByteSize
    gpu_request: int = Field(ge=0, default=0)

    class Config:
        """Configuration."""

        extra = "ignore"


class _ServerOptionsCpu(BaseModel):
    options: list[float] = Field(min_length=1)

    class Config:
        extra = "ignore"

    @validator("options", pre=False, each_item=True)
    def greater_than_zero(cls, val: Union[float, int]) -> Union[float, int]:
        return _check_greater_than_zero(cls, val)


class _ServerOptionsGpu(BaseModel):
    options: list[int] = Field(min_length=1)

    class Config:
        extra = "ignore"

    @validator("options", pre=False, each_item=True)
    def greater_than_or_equal_to_zero(cls, v: int) -> int:
        if v < 0:
            raise ValueError(f"The provided value should be greater than or equal to zero, instead it was {v}.")
        return v


class _ServerOptionsBytes(BaseModel):
    options: list[ByteSize] = Field(min_length=1)

    class Config:
        extra = "ignore"

    @validator("options", pre=True)
    def convert_units(cls, vals: list[str]) -> list[str]:
        for ival, val in enumerate(vals):
            if isinstance(val, str) and val.strip().endswith("i"):
                vals[ival] = val.strip() + "b"
        return vals

    @validator("options", pre=False, each_item=True)
    def greater_than_zero(cls, val: Union[float, int]) -> Union[float, int]:
        return _check_greater_than_zero(cls, val)


class ServerOptions(BaseModel):
    """Used to parse the server options passed to the notebook service in the Helm values."""

    cpu_request: _ServerOptionsCpu
    mem_request: _ServerOptionsBytes
    disk_request: _ServerOptionsBytes
    gpu_request: _ServerOptionsGpu = Field(default_factory=lambda: _ServerOptionsGpu(options=[0]))

    class Config:
        """Configuration."""

        extra = "ignore"

    def find_largest_attribute(self) -> str:
        """Find the attribute with the largest number of choices."""
        options = ((k, v.get("options", [])) for k, v in self.model_dump().items() if k != "disk_request")
        largest_list = max(options, key=lambda t: len(t[1]))[0]
        return largest_list


def _get_classname() -> Generator[str, None, None]:
    yield "small"
    yield "medium"
    yield "large"
    count = 1
    while True:
        yield "x" * count + "large"
        count += 1


def generate_default_resource_pool(
    server_options: ServerOptions, defaults: ServerOptionsDefaults
) -> models.UnsavedResourcePool:
    """Generate a resource pool from the notebook service style server options."""
    clses: list[models.UnsavedResourceClass] = []
    largest_attribute = server_options.find_largest_attribute()
    options_xref = {
        "cpu_request": "cpu",
        "mem_request": "memory",
        "gpu_request": "gpu",
    }
    class_names = _get_classname()
    largest_attribute_options = getattr(server_options, largest_attribute).options
    max_storage = round(max(server_options.disk_request.options) / 1_000_000_000)
    for ival, val in enumerate(sorted(largest_attribute_options)):
        cls = {}
        for old_name, new_name in options_xref.items():
            if largest_attribute == old_name:
                cls[new_name] = val
            else:
                options = getattr(server_options, old_name).options
                try:
                    cls[new_name] = options[ival]
                except IndexError:
                    cls[new_name] = options[-1]
            if new_name == "memory":
                cls[new_name] = round(cls[new_name] / 1_000_000_000)
        cls["name"] = next(class_names)
        cls["max_storage"] = max_storage
        cls["default_storage"] = round(defaults.disk_request / 1_000_000_000)
        clses.append(models.UnsavedResourceClass(**cls))
    clses.append(
        models.UnsavedResourceClass(
            cpu=defaults.cpu_request,
            memory=round(defaults.mem_request / 1_000_000_000),
            gpu=defaults.gpu_request,
            name="default",
            default=True,
            max_storage=max_storage,
            default_storage=round(defaults.disk_request / 1_000_000_000),
        )
    )
    return models.UnsavedResourcePool(
        classes=clses,
        default=True,
        public=True,
        name="default",
        platform=DEFAULT_RUNTIME_PLATFORM,
    )
