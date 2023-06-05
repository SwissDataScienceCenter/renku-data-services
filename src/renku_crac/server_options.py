"""Validation and parsing for the notebook service (old) style of server options and defaults.

The purpose of this is to be able to create resource
pools and classes based on the old server options until the admin UI interface
is added.
"""
from typing import Any, List, Set

from pydantic import BaseModel, ByteSize, Extra, Field, validator

import models


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

        extra = Extra.ignore


class _ServerOptionsCpu(BaseModel):
    options: List[float] = Field(min_items=1)

    class Config:
        extra = Extra.ignore

    @validator("options", pre=False, each_item=True)
    def greater_than_zero(cls, val):
        return _check_greater_than_zero(cls, val)


class _ServerOptionsGpu(BaseModel):
    options: List[int] = Field(min_items=1)

    class Config:
        extra = Extra.ignore

    @validator("options", pre=False, each_item=True)
    def greater_than_or_equal_to_zero(cls, v):
        if v < 0:
            raise ValueError(f"The provided value should be greater than or equal to zero, instead it was {v}.")
        return v


class _ServerOptionsBytes(BaseModel):
    options: List[ByteSize] = Field(min_items=1)

    class Config:
        extra = Extra.ignore

    @validator("options", pre=True)
    def convert_units(cls, vals):
        for ival, val in enumerate(vals):
            if isinstance(val, str) and val.strip().endswith("i"):
                vals[ival] = val.strip() + "b"
        return vals

    @validator("options", pre=False, each_item=True)
    def greater_than_zero(cls, val):
        return _check_greater_than_zero(cls, val)


class ServerOptions(BaseModel):
    """Used to parse the server options passed to the notebook service in the Helm values."""

    cpu_request: _ServerOptionsCpu
    mem_request: _ServerOptionsBytes
    disk_request: _ServerOptionsBytes
    gpu_request: _ServerOptionsGpu = Field(default_factory=lambda: _ServerOptionsGpu(options=[0]))

    class Config:
        """Configuration."""

        extra = Extra.ignore

    def find_largest_attribute(self) -> str:
        """Find the attribute with the largest number of choices."""
        max_elems = 0
        largest_list = ""
        for k, v in self.dict().items():
            options = v.get("options", [])
            if k == "disk_request":
                continue
            if len(options) > max_elems:
                max_elems = len(options)
                largest_list = k
        return largest_list


class _ClassNameIter:
    def __init__(self):
        self._vals = ["small", "medium", "large"]
        self._current_ind = 0

    def __iter__(self):
        self._current_ind = 0
        return self

    def __next__(self):
        curr_ind = self._current_ind
        self._current_ind += 1
        if curr_ind >= len(self._vals):
            return ("x" * (curr_ind - len(self._vals) + 1)) + self._vals[-1]
        return self._vals[curr_ind]


def generate_default_resource_pool(
    server_options: ServerOptions, defaults: ServerOptionsDefaults
) -> models.ResourcePool:
    """Generate a resource pool from the notebook service style server options."""
    clses: Set[models.ResourceClass] = set()
    largest_attribute = server_options.find_largest_attribute()
    options_xref = {
        "cpu_request": "cpu",
        "mem_request": "memory",
        "gpu_request": "gpu",
    }
    class_names = _ClassNameIter()
    largest_attribute_options = getattr(getattr(server_options, largest_attribute), "options")
    max_storage = round(sorted(server_options.disk_request.options)[-1] / 1_000_000_000)
    for ival, val in sorted(enumerate(largest_attribute_options)):
        cls = {}
        for old_name, new_name in options_xref.items():
            if largest_attribute == old_name:
                cls[new_name] = val
            else:
                options = getattr(getattr(server_options, old_name), "options")
                try:
                    cls[new_name] = options[ival]
                except IndexError:
                    cls[new_name] = options[-1]
            if new_name == "memory":
                cls[new_name] = round(cls[new_name] / 1_000_000_000)
        cls["name"] = next(class_names)
        cls["max_storage"] = max_storage
        cls["default_storage"] = round(defaults.disk_request / 1_000_000_000)
        clses.add(models.ResourceClass.from_dict(cls))
    clses.add(
        models.ResourceClass(
            cpu=defaults.cpu_request,
            memory=round(defaults.mem_request / 1_000_000_000),
            gpu=defaults.gpu_request,
            name="default",
            default=True,
            max_storage=max_storage,
            default_storage=round(defaults.disk_request / 1_000_000_000),
        )
    )
    return models.ResourcePool(
        classes=clses,
        default=True,
        public=True,
        name="default",
    )
