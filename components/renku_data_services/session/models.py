"""Models for Sessions."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Self

from pydantic import BaseModel, model_validator
from ulid import ULID

from renku_data_services import errors


class EnvironmentKind(Enum):
    """Environment kind enum."""

    global_environment = "global_environment"
    container_image = "container_image"


@dataclass(frozen=True, eq=True, kw_only=True)
class Member(BaseModel):
    """Member model."""

    id: str


@dataclass(frozen=True, eq=True, kw_only=True)
class UnsavedEnvironment(BaseModel):
    """Session environment model that isn't in the db yet."""

    name: str
    creation_date: datetime
    description: str | None
    container_image: str
    default_url: str | None
    created_by: Member


@dataclass(frozen=True, eq=True, kw_only=True)
class Environment(UnsavedEnvironment):  # type: ignore[misc]
    """Session environment model."""

    id: ULID


@dataclass(frozen=True, eq=True, kw_only=True)
class UnsavedSessionLauncher(BaseModel):
    """Session launcher model that isn't in the db yet."""

    project_id: ULID
    name: str
    creation_date: datetime
    description: str | None
    environment_kind: EnvironmentKind
    environment_id: str | None
    resource_class_id: int | None
    container_image: str | None
    default_url: str | None
    created_by: Member

    @model_validator(mode="after")
    def check_launcher_environment_kind(self) -> Self:
        """Validates the environment of a launcher."""

        environment_kind = self.environment_kind
        environment_id = self.environment_id
        container_image = self.container_image

        if environment_kind == EnvironmentKind.global_environment and environment_id is None:
            raise errors.ValidationError(message="'environment_id' not set when environment_kind=global_environment")

        if environment_kind == EnvironmentKind.container_image and container_image is None:
            raise errors.ValidationError(message="'container_image' not set when environment_kind=container_image")

        return self


@dataclass(frozen=True, eq=True, kw_only=True)
class SessionLauncher(UnsavedSessionLauncher):  # type: ignore[misc]
    """Session launcher model."""

    id: ULID
