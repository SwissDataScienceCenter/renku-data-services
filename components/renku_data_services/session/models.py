"""Models for sessions."""

import re
import typing
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import PurePosixPath

from ulid import ULID

from renku_data_services import errors
from renku_data_services.base_models.core import ResetType
from renku_data_services.session import crs


@dataclass(frozen=True, eq=True, kw_only=True)
class Member:
    """Member model."""

    id: str


class EnvironmentKind(StrEnum):
    """The type of environment."""

    GLOBAL = "GLOBAL"
    CUSTOM = "CUSTOM"


class EnvironmentImageSource(StrEnum):
    """The source of the environment image."""

    image = "image"
    build = "build"


class BuilderVariant(StrEnum):
    """The type of environment builder."""

    python = "python"


class FrontendVariant(StrEnum):
    """The environment frontend choice."""

    vscodium = "vscodium"


@dataclass(kw_only=True, frozen=True, eq=True)
class UnsavedBuildParameters:
    """The parameters of a build."""

    repository: str
    builder_variant: str
    frontend_variant: str


@dataclass(kw_only=True, frozen=True, eq=True)
class BuildParameters(UnsavedBuildParameters):
    """BuildParameters saved in the database."""

    id: ULID


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
    environment_image_source: EnvironmentImageSource
    args: list[str] | None = None
    command: list[str] | None = None
    is_archived: bool = False

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
    build_parameters: BuildParameters | None
    build_parameters_id: ULID | None


@dataclass(kw_only=True, frozen=True, eq=True)
class BuildParametersPatch:
    """Patch for parameters of a build."""

    repository: str | None = None
    builder_variant: str | None = None
    frontend_variant: str | None = None


@dataclass(eq=True, kw_only=True)
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
    is_archived: bool | None = None
    build_parameters: BuildParametersPatch | None = None
    environment_image_source: EnvironmentImageSource | None = None


def validate_env_variables(env_variables: dict[str, typing.Any] | None) -> list[str] | None:
    """Validate environment variables."""

    if env_variables is None:
        return None

    # TODO: Verify that these limits are compatible with k8s
    MAX_NUMBER_ENV_VARIABLES = 32
    MAX_LENGTH_ENV_VARIABLES_NAME = 256
    MAX_LENGTH_ENV_VARIABLES_VALUE = 1000

    # see https://pubs.opengroup.org/onlinepubs/9699919799/basedefs/V1_chap03.html#tag_03_231
    variable_regex = r"^[a-zA-Z_][a-zA-Z0-9_]*$"
    variable_name_matcher = re.compile(variable_regex)

    errors = []
    if len(env_variables) > MAX_NUMBER_ENV_VARIABLES:
        errors.append(f"Cannot have more than {MAX_NUMBER_ENV_VARIABLES} env variables.")
    has_non_str_value = False
    for value in env_variables.values():
        if value is not None and not isinstance(value, str):
            errors.append("Env variable values must be strings.")
            has_non_str_value = True
            break
    if has_non_str_value:
        return errors
    for name, value in env_variables.items():
        if len(name) > MAX_LENGTH_ENV_VARIABLES_NAME:
            errors.append(f"Env variable name '{name}' is longer than {MAX_LENGTH_ENV_VARIABLES_NAME} characters.")
        if name.upper().startswith("RENKU"):
            errors.append(f"Env variable name '{name}' should not start with 'RENKU'.")
        if variable_name_matcher.match(name) is None:
            errors.append(f"Env variable name '{name}' must match the regex '{variable_regex}'.")
        if value and len(value) > MAX_LENGTH_ENV_VARIABLES_VALUE:
            errors.append(
                f"Env variable value for '{name}' is longer than {MAX_LENGTH_ENV_VARIABLES_VALUE} characters."
            )

    if len(errors) > 0:
        return errors

    return None


@dataclass(frozen=True, eq=True, kw_only=True)
class UnsavedSessionLauncher:
    """Session launcher model that has not been persisted in the DB."""

    project_id: ULID
    name: str
    description: str | None
    resource_class_id: int | None
    disk_storage: int | None
    env_variables: dict[str, str | None] | None
    environment: str | UnsavedEnvironment | UnsavedBuildParameters
    """When a string is passed for the environment it should be the ID of an existing environment."""

    def __post_init__(self) -> None:
        env_variable_errors = validate_env_variables(self.env_variables)
        if env_variable_errors:
            if len(env_variable_errors) == 1:
                raise errors.ValidationError(message=env_variable_errors[0])
            raise errors.ValidationError(message="\n".join(env_variable_errors))


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
    # NOTE: When unsaved environment is used it means a brand-new environment should be created for the
    # launcher with the update of the launcher.
    environment: str | EnvironmentPatch | UnsavedEnvironment | UnsavedBuildParameters | None = None
    resource_class_id: int | None | ResetType = None
    disk_storage: int | None | ResetType = None
    env_variables: dict[str, str | None] | None | ResetType = None


@dataclass(frozen=True, eq=True, kw_only=True)
class BuildResult:
    """Model to represent the result of a build of a container image."""

    image: str
    completed_at: datetime
    repository_url: str
    repository_git_commit_sha: str


class BuildStatus(StrEnum):
    """The status of a build."""

    in_progress = "in_progress"
    failed = "failed"
    cancelled = "cancelled"
    succeeded = "succeeded"


@dataclass(frozen=True, eq=True, kw_only=True)
class Build:
    """Model to represent the build of a container image."""

    id: ULID
    environment_id: ULID
    created_at: datetime
    status: BuildStatus
    result: BuildResult | None = None
    error_reason: str | None = None

    @property
    def k8s_name(self) -> str:
        """Returns the name of the corresponding Shipwright BuildRun."""
        name = f"renku-{self.id}"
        return name.lower()


@dataclass(frozen=True, eq=True, kw_only=True)
class UnsavedBuild:
    """Model to represent a requested container image build."""

    environment_id: ULID


@dataclass(frozen=True, eq=True, kw_only=True)
class BuildPatch:
    """Model to represent the requested update to a container image build."""

    status: BuildStatus | None = None


@dataclass(frozen=True, eq=True, kw_only=True)
class ShipwrightBuildRunParams:
    """Model to represent the parameters used to create a new Shipwright BuildRun."""

    name: str
    git_repository: str
    run_image: str
    output_image: str
    build_strategy_name: str
    push_secret_name: str
    retention_after_failed: timedelta | None = None
    retention_after_succeeded: timedelta | None = None
    build_timeout: timedelta | None = None
    node_selector: dict[str, str] | None = None
    tolerations: list[crs.Toleration] | None = None
    labels: dict[str, str] | None = None
    annotations: dict[str, str] | None = None


@dataclass(frozen=True, eq=True, kw_only=True)
class ShipwrightBuildStatusUpdateContent:
    """Model to represent an update about a build from Shipwright."""

    status: BuildStatus
    result: BuildResult | None = None
    completed_at: datetime | None = None
    error_reason: str | None = None


@dataclass(frozen=True, eq=True, kw_only=True)
class ShipwrightBuildStatusUpdate:
    """Model to represent an update about a build from Shipwright."""

    update: ShipwrightBuildStatusUpdateContent | None
    """The update about a build.

    None represents "no update"."""
