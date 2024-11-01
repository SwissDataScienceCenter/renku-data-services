"""Models for sessions."""

from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, model_validator
from ulid import ULID

from renku_data_services import errors
from renku_data_services.session.apispec import EnvironmentKind


@dataclass(frozen=True, eq=True, kw_only=True)
class Member:
    """Member model."""

    id: str


@dataclass(frozen=True, eq=True, kw_only=True)
class UnsavedEnvironment:
    """A session environment that hasn't been stored in the database."""

    name: str
    description: str | None
    container_image: str
    default_url: str | None


@dataclass(frozen=True, eq=True, kw_only=True)
class Environment(UnsavedEnvironment):
    """Session environment model."""

    id: str
    creation_date: datetime
    created_by: Member


@dataclass(frozen=True, eq=True, kw_only=True)
class EnvironmentPatch:
    """Model for changes requested on a session environment."""

    name: str | None = None
    description: str | None = None
    container_image: str | None = None
    default_url: str | None = None


class UnsavedSessionLauncher(BaseModel):
    """A session launcher that hasn't been stored in the database."""

    project_id: ULID
    name: str
    description: str | None
    environment_kind: EnvironmentKind
    environment_id: str | None
    resource_class_id: int | None
    container_image: str | None
    default_url: str | None

    @model_validator(mode="after")
    def check_launcher_environment_kind(self) -> "UnsavedSessionLauncher":
        """Validates the environment of a launcher."""

        environment_kind = self.environment_kind
        environment_id = self.environment_id
        container_image = self.container_image

        if environment_kind == EnvironmentKind.global_environment and environment_id is None:
            raise errors.ValidationError(message="'environment_id' not set when environment_kind=global_environment")

        if environment_kind == EnvironmentKind.container_image and container_image is None:
            raise errors.ValidationError(message="'container_image' not set when environment_kind=container_image")

        return self


class SessionLauncher(UnsavedSessionLauncher):
    """Session launcher model."""

    id: ULID
    creation_date: datetime
    created_by: Member


@dataclass(frozen=True, eq=True, kw_only=True)
class SessionLauncherPatch:
    """Model for changes requested on a session launcher."""

    name: str | None = None
    description: str | None = None
    environment_kind: EnvironmentKind | None = None
    environment_id: str | None = None
    resource_class_id: int | None = None
    container_image: str | None = None
    default_url: str | None = None
