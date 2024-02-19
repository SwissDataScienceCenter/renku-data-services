"""Models for Sessions."""

from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, model_validator

from renku_data_services import errors
from renku_data_services.session.apispec import EnvironmentKind


@dataclass(frozen=True, eq=True, kw_only=True)
class Member(BaseModel):
    """Member model."""

    id: str


@dataclass(frozen=True, eq=True, kw_only=True)
class SessionEnvironment(BaseModel):
    """Session environment model."""

    id: str
    name: str
    creation_date: datetime
    description: str | None
    container_image: str
    created_by: Member


@dataclass(frozen=True, eq=True, kw_only=True)
class NewSessionEnvironment(BaseModel):
    """New session environment model."""

    name: str
    creation_date: datetime
    description: str | None
    container_image: str
    created_by: Member


@dataclass(frozen=True, eq=True, kw_only=True)
class SessionLauncher(BaseModel):
    """Session launcher model."""

    id: str
    project_id: str
    name: str
    creation_date: datetime
    description: str | None
    environment_kind: EnvironmentKind
    environment_id: str | None
    container_image: str | None
    created_by: Member

    @model_validator(mode="after")
    def check_launcher_environment_kind(self):
        """Validates the environment."""
        _check_launcher_environment_kind(self)
        return self


@dataclass(frozen=True, eq=True, kw_only=True)
class NewSessionLauncher(BaseModel):
    """New session launcher model."""

    project_id: str
    name: str
    creation_date: datetime
    description: str | None
    environment_kind: EnvironmentKind
    environment_id: str | None
    container_image: str | None
    created_by: Member

    @model_validator(mode="after")
    def check_launcher_environment_kind(self):
        """Validates the environment."""
        _check_launcher_environment_kind(self)
        return self


def _check_launcher_environment_kind(model: SessionLauncher | NewSessionLauncher) -> None:
    """Validates the environment of a launcher."""

    environment_kind = model.environment_kind
    environment_id = model.environment_id
    container_image = model.container_image

    if environment_kind == EnvironmentKind.global_environment and environment_id is None:
        raise errors.ValidationError(message="'environment_id' not set when environment_kind=global_environment")

    if environment_kind == EnvironmentKind.container_image and container_image is None:
        raise errors.ValidationError(message="'container_image' not set when environment_kind=container_image")
