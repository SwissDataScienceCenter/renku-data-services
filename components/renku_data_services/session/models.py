"""Models for Sessions."""

from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, model_validator
from ulid import ULID
from enum import StrEnum
from pathlib import PurePosixPath

from renku_data_services import errors


class EnvironmentKind(StrEnum):
    """The type of environment."""

    GLOBAL: str = "GLOBAL"
    CUSTOM: str = "CUSTOM"


@dataclass(kw_only=True, frozen=True, eq=True)
class BaseEnvironment:
    """Base session environment model."""

    name: str
    description: str | None
    container_image: str
    default_url: str
    port: int
    working_directory: PurePosixPath
    mount_directory: PurePosixPath
    uid: int
    gid: int
    environment_kind: EnvironmentKind


@dataclass(kw_only=True, frozen=True, eq=True)
class UnsavedEnvironment(BaseEnvironment):
    """Session environment model that has not been saved."""

    port: int = 8888
    description: str | None = None
    working_directory: PurePosixPath = PurePosixPath("/home/jovyan/work")
    mount_directory: PurePosixPath = PurePosixPath("/home/jovyan/work")
    uid: int = 1000
    gid: int = 1000

    def __post_init__(self) -> None:
        if not self.working_directory.is_absolute():
            raise errors.ValidationError(message="The working directory for a session is supposed to be absolute")
        if not self.mount_directory.is_absolute():
            raise errors.ValidationError(message="The mount directory for a session is supposed to be absolute")
        if self.working_directory.is_reserved():
            raise errors.ValidationError(
                message="The requested value for the working directory is reserved by the OS and cannot be used."
            )
        if self.mount_directory.is_reserved():
            raise errors.ValidationError(
                message="The requested value for the mount directory is reserved by the OS and cannot be used."
            )


@dataclass(kw_only=True, frozen=True, eq=True)
class Environment(BaseEnvironment):
    """Session environment model that has been saved in the DB."""

    id: str
    creation_date: datetime
    created_by: str


@dataclass(frozen=True, eq=True, kw_only=True)
class BaseSessionLauncher:
    """Session launcher model."""

    id: ULID | None
    project_id: str
    name: str
    description: str | None
    environment: str | UnsavedEnvironment | Environment
    resource_class_id: int | None


@dataclass(frozen=True, eq=True, kw_only=True)
class UnsavedSessionLauncher(BaseSessionLauncher):
    """Session launcher model that has not been persisted in the DB."""

    environment: str | UnsavedEnvironment
    """When a string is passed for the environment it should be the ID of an existing environment."""


@dataclass(frozen=True, eq=True, kw_only=True)
class SessionLauncher(BaseSessionLauncher):
    """Session launcher model that has been already saved in the DB."""

    id: str
    creation_date: datetime
    created_by: str
    environment: Environment
