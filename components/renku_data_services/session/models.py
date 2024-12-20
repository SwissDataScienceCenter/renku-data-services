"""Models for sessions."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import PurePosixPath

from ulid import ULID

from renku_data_services import errors
from renku_data_services.base_models.core import ResetType


@dataclass(frozen=True, eq=True, kw_only=True)
class Member:
    """Member model."""

    id: str


class EnvironmentKind(StrEnum):
    """The type of environment."""

    GLOBAL: str = "GLOBAL"
    CUSTOM: str = "CUSTOM"


@dataclass(kw_only=True, frozen=True, eq=True)
class UnsavedEnvironment:
    """Session environment model that has not been saved."""

    name: str
    description: str | None = None
    container_image: str
    default_url: str
    port: int = 8888
    working_directory: PurePosixPath | None = None
    mount_directory: PurePosixPath | None = None
    uid: int = 1000
    gid: int = 1000
    environment_kind: EnvironmentKind
    args: list[str] | None = None
    command: list[str] | None = None

    def __post_init__(self) -> None:
        if self.working_directory and not self.working_directory.is_absolute():
            raise errors.ValidationError(message="The working directory for a session is supposed to be absolute")
        if self.mount_directory and not self.mount_directory.is_absolute():
            raise errors.ValidationError(message="The mount directory for a session is supposed to be absolute")
        if self.working_directory and self.working_directory.is_reserved():
            raise errors.ValidationError(
                message="The requested value for the working directory is reserved by the OS and cannot be used."
            )
        if self.mount_directory and self.mount_directory.is_reserved():
            raise errors.ValidationError(
                message="The requested value for the mount directory is reserved by the OS and cannot be used."
            )


@dataclass(frozen=True, eq=True, kw_only=True)
class Environment(UnsavedEnvironment):
    """Session environment model."""

    id: ULID
    creation_date: datetime
    created_by: Member
    container_image: str
    default_url: str
    port: int
    working_directory: PurePosixPath | None
    mount_directory: PurePosixPath | None
    uid: int
    gid: int


@dataclass(frozen=True, eq=True, kw_only=True)
class EnvironmentPatch:
    """Model for changes requested on a session environment."""

    name: str | None = None
    description: str | None = None
    container_image: str | None = None
    default_url: str | None = None
    port: int | None = None
    working_directory: PurePosixPath | ResetType | None = None
    mount_directory: PurePosixPath | ResetType | None = None
    uid: int | None = None
    gid: int | None = None
    args: list[str] | None | ResetType = None
    command: list[str] | None | ResetType = None


@dataclass(frozen=True, eq=True, kw_only=True)
class UnsavedSessionLauncher:
    """Session launcher model that has not been persisted in the DB."""

    project_id: ULID
    name: str
    description: str | None
    resource_class_id: int | None
    environment: str | UnsavedEnvironment
    """When a string is passed for the environment it should be the ID of an existing environment."""


@dataclass(frozen=True, eq=True, kw_only=True)
class SessionLauncher(UnsavedSessionLauncher):
    """Session launcher model."""

    id: ULID
    creation_date: datetime
    created_by: Member
    environment: Environment


@dataclass(frozen=True, eq=True, kw_only=True)
class SessionLauncherPatch:
    """Model for changes requested on a session launcher."""

    name: str | None = None
    description: str | None = None
    # NOTE: When unsaved environment is used it means a brand new environment should be created for the
    # launcher with the update of the launcher.
    environment: str | EnvironmentPatch | UnsavedEnvironment | None = None
    resource_class_id: int | None | ResetType = None
