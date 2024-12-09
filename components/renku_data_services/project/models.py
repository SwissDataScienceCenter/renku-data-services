"""Models for project."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Literal

from ulid import ULID

from renku_data_services.authz.models import Visibility
from renku_data_services.namespace.models import Namespace
from renku_data_services.utils.etag import compute_etag_from_timestamp

Repository = str


@dataclass(frozen=True, eq=True, kw_only=True)
class BaseProject:
    """Base Project model."""

    name: str
    slug: str
    visibility: Visibility
    created_by: str
    creation_date: datetime = field(default_factory=lambda: datetime.now(UTC).replace(microsecond=0))
    updated_at: datetime | None = field(default=None)
    repositories: list[Repository] = field(default_factory=list)
    description: str | None = None
    keywords: list[str] | None = None
    documentation: str | None = None
    template_id: ULID | None = None
    is_template: bool = False
    secrets_mount_directory: PurePosixPath | None

    @property
    def etag(self) -> str | None:
        """Entity tag value for this project object."""
        if self.updated_at is None:
            return None
        return compute_etag_from_timestamp(self.updated_at)


@dataclass(frozen=True, eq=True, kw_only=True)
class Project(BaseProject):
    """Model for a project which has been persisted in the database."""

    id: ULID
    namespace: Namespace
    secrets_mount_directory: PurePosixPath


@dataclass(frozen=True, eq=True, kw_only=True)
class UnsavedProject(BaseProject):
    """A project that hasn't been stored in the database."""

    namespace: str


@dataclass(frozen=True, eq=True, kw_only=True)
class ProjectPatch:
    """Model for changes requested on a project."""

    name: str | None
    namespace: str | None
    visibility: Visibility | None
    repositories: list[Repository] | None
    description: str | None
    keywords: list[str] | None
    documentation: str | None
    template_id: Literal[""] | None
    is_template: bool | None
    secrets_mount_directory: PurePosixPath | None


@dataclass
class DeletedProject:
    """Indicates that a project was deleted."""

    id: ULID


@dataclass
class ProjectUpdate:
    """Indicates that a project has been updated and retains the old and new values."""

    old: Project
    new: Project


@dataclass
class ProjectPermissions:
    """The permissions of a user on a given project."""

    write: bool
    delete: bool
    change_membership: bool


@dataclass(frozen=True, eq=True, kw_only=True)
class UnsavedSessionSecretSlot:
    """Session secret slot model that has not been persisted."""

    project_id: ULID
    name: str | None
    description: str | None
    filename: str


@dataclass(frozen=True, eq=True, kw_only=True)
class SessionSecretSlot(UnsavedSessionSecretSlot):
    """Session secret slot model that has been persisted."""

    id: ULID
    created_by_id: str
    creation_date: datetime
    updated_at: datetime

    @property
    def etag(self) -> str:
        """Entity tag value for this session secret slot object."""
        return compute_etag_from_timestamp(self.updated_at, include_quotes=True)


@dataclass(frozen=True, eq=True, kw_only=True)
class SessionSecretSlotPatch:
    """Model for changes requested on a session secret slot."""

    name: str | None
    description: str | None
    filename: str | None


@dataclass(frozen=True, eq=True, kw_only=True)
class SessionSecret:
    """Session secret model that has been persisted."""

    secret_slot: SessionSecretSlot
    secret_id: ULID


@dataclass(frozen=True, eq=True, kw_only=True)
class SessionSecretPatchExistingSecret:
    """Model for changes requested on a session secret."""

    secret_slot_id: ULID
    secret_id: ULID


@dataclass(frozen=True, eq=True, kw_only=True)
class SessionSecretPatchSecretValue:
    """Model for changes requested on a session secret."""

    secret_slot_id: ULID
    value: str | None
