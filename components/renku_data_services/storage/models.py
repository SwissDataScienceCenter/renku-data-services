"""Models for storage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath

from ulid import ULID

from renku_data_services.base_models.bytesize import ByteSize
from renku_data_services.base_models.core import (
    ProjectPath,
)
from renku_data_services.utils.etag import compute_etag_from_fields


@dataclass(frozen=True, eq=True, kw_only=True)
class UnsavedProjectStorage:
    """Project storage definition."""

    namespace_path: ProjectPath
    size: ByteSize
    mount_path: PurePosixPath


@dataclass(frozen=True, eq=True, kw_only=True)
class ProjectStoragePatch:
    """Model for changes requested on a project storage."""

    size: ByteSize | None
    mount_path: PurePosixPath | None


@dataclass(frozen=True, eq=True, kw_only=True)
class ProjectStorage:
    """Stored project storage information."""

    id: ULID
    project_id: ULID
    storage_class: str
    size: ByteSize
    mount_path: PurePosixPath
    created_by: str
    creation_date: datetime
    updated_at: datetime

    @property
    def etag(self) -> str:
        """Entity tag value for this project storage object."""
        return compute_etag_from_fields(
            self.updated_at, self.project_id, self.storage_class, self.size.to_bytes(), self.mount_path.as_posix()
        )


@dataclass(frozen=True, eq=True, kw_only=True)
class DeletedProjectStorage:
    """A project storage that has been deleted."""

    project_id: ULID


@dataclass(frozen=True, eq=True, kw_only=True)
class ProjectStorageAllow:
    """Allowed project storage with max size."""

    project_ref: ProjectRef
    max_size: ByteSize
    updated_at: datetime

    @property
    def etag(self) -> str:
        """Entity tag value for this project storage allow object."""
        return compute_etag_from_fields(self.updated_at, self.project_ref, self.max_size.to_bytes())


@dataclass(frozen=True, eq=True, kw_only=True)
class ProjectStorageAllowDetail:
    """Allowed project storage with max size."""

    project_id: ULID
    max_size: ByteSize
    name: str
    namespace_path: ProjectPath
    updated_at: datetime

    @classmethod
    def create(
        cls,
        project_id: ULID,
        max_size: ByteSize,
        name: str,
        namespace_slug: str,
        project_slug: str,
        updated_at: datetime,
    ) -> ProjectStorageAllowDetail:
        """Create an instance with the project path given as two strings."""
        np = ProjectPath.from_strings(namespace_slug, project_slug)
        return ProjectStorageAllowDetail(
            project_id=project_id, max_size=max_size, name=name, namespace_path=np, updated_at=updated_at
        )

    @property
    def etag(self) -> str:
        """Entity tag value for this project storage allow object."""
        return compute_etag_from_fields(self.updated_at, self.project_id, self.max_size.to_bytes())


@dataclass(frozen=True, eq=True, kw_only=True)
class ProjectStorageAllowPatch:
    """Model for changes requested on a project storage allow entry."""

    max_size: ByteSize | None


@dataclass(frozen=True, eq=True, kw_only=True)
class ProjectStorageAllowUpdate:
    """Return data when updating an allow entry."""

    old: ProjectStorageAllowDetail
    new: ProjectStorageAllowDetail


@dataclass(frozen=True, eq=True, kw_only=True)
class ProjectRef:
    """A reference to a project."""

    ref: ULID | ProjectPath

    def __str__(self) -> str:
        return f"ProjectRef({self.ref})"

    @classmethod
    def from_id(cls, id: ULID) -> ProjectRef:
        """Create a project ref from an id."""
        return ProjectRef(ref=id)

    @classmethod
    def from_id_str(cls, id: str) -> ProjectRef:
        """Create a project ref from an id."""
        return cls.from_id(ULID.from_str(id))

    @classmethod
    def from_slug(cls, slug: ProjectPath) -> ProjectRef:
        """Create a project ref from a path."""
        return ProjectRef(ref=slug)

    @classmethod
    def from_slug_str(cls, slug: str) -> ProjectRef:
        """Create a project ref from a path."""
        return ProjectRef(ref=ProjectPath.parse(slug))
