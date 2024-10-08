"""Models for Sessions."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import PurePosixPath

from ulid import ULID

from renku_data_services import errors
from renku_data_services.base_models.core import ResetType


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
    args: list[str] | None = None
    command: list[str] | None = None


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

    id: ULID
    creation_date: datetime
    created_by: str


@dataclass(kw_only=True, frozen=True, eq=True)
class EnvironmentUpdate:
    """Model for the update of some or all parts of an environment."""

    name: str | None = None
    description: str | None = None
    container_image: str | None = None
    default_url: str | None = None
    port: int | None = None
    working_directory: PurePosixPath | None = None
    mount_directory: PurePosixPath | None = None
    uid: int | None = None
    gid: int | None = None
    args: list[str] | None | ResetType = None
    command: list[str] | None | ResetType = None


@dataclass(frozen=True, eq=True, kw_only=True)
class BaseSessionLauncher:
    """Session launcher model."""

    project_id: ULID
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

    id: ULID
    creation_date: datetime
    created_by: str
    environment: Environment


@dataclass(frozen=True, eq=True, kw_only=True)
class SessionLauncherUpdate:
    """Model for the update of a session launcher."""

    name: str | None = None
    description: str | None = None
    # NOTE: When unsaved environment is used it means a brand new environment should be created for the
    # launcher with the update of the launcher.
    environment: str | EnvironmentUpdate | UnsavedEnvironment | None = None
    resource_class_id: int | None | ResetType = None
