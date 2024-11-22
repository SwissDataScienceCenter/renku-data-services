"""Models for project."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Optional

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
    description: Optional[str] = None
    keywords: Optional[list[str]] = None
    documentation: Optional[str] = None
    template_id: Optional[ULID] = None

    @property
    def etag(self) -> str | None:
        """Entity tag value for this project object."""
        if self.updated_at is None:
            return None
        return compute_etag_from_timestamp(self.updated_at)


@dataclass(frozen=True, eq=True, kw_only=True)
class Project(BaseProject):
    """Base Project model."""

    id: ULID
    namespace: Namespace


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
