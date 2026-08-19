"""Business logic for project storage."""

from __future__ import annotations

from datetime import datetime
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from ulid import ULID

from renku_data_services import errors
from renku_data_services.base_models.bytesize import ByteSize
from renku_data_services.base_models.core import (
    ProjectPath,
)
from renku_data_services.storage import apispec, models

if TYPE_CHECKING:
    pass


def _validate_mount_path(path: str | None) -> None:
    #
    invalid_prefixes = [
        "/",
        "/bin",
        "/sbin",
        "/usr",
        "/lib",
        "/lib64",
        "/boot",
        "/etc",
        "/proc",
        "/sys",
        "/dev",
        "/run",
        "/sys",
        "/var",
        "/tmp",  # nosec B108
        "/home",
        "/root",
    ]
    if not path or path == "":
        raise errors.ValidationError(message="The mount path must not be empty")

    for prefix in invalid_prefixes:
        if path == prefix or path.startswith(f"{prefix}/"):
            raise errors.ValidationError(message=f"The mount path is invalid: '{path}'")


def validate_unsaved_project_storage(body: apispec.ProjectStoragePost) -> models.UnsavedProjectStorage:
    """Validate the user input for a new project storage definition.

    The namespace must be a project namespace. The project must be
    enabled for project storages and the user must be an owner.
    """

    _validate_mount_path(body.mount_path)

    namespace_path = ProjectPath.parse(body.namespace)
    return models.UnsavedProjectStorage(
        namespace_path=namespace_path, size=ByteSize.from_gibi(body.size), mount_path=PurePosixPath(body.mount_path)
    )


def validate_project_storage_patch(
    existing: models.ProjectStorage, body: apispec.ProjectStoragePatch
) -> models.ProjectStoragePatch:
    """Validate a patch of a project storage entry."""
    size = ByteSize.from_gibi(body.size) if body.size else None
    if size and size < ByteSize.from_gibi(1):
        raise errors.ValidationError(message="The size must be at least 1GB")
    mount_path = PurePosixPath(body.mount_path) if body.mount_path else None
    if mount_path:
        _validate_mount_path(body.mount_path)
    return models.ProjectStoragePatch(size=size, mount_path=mount_path)


def validate_project_storage_allow_post(body: apispec.ProjectStorageAllowPost) -> models.ProjectStorageAllow:
    """Validate."""
    allow = models.ProjectStorageAllow(
        project_id=ULID.from_str(body.project_id), max_size=ByteSize.from_gibi(body.max_size), updated_at=datetime.now()
    )
    if allow.max_size < ByteSize.from_gibi(1):
        raise errors.ValidationError(message=f"The maximum size must be at least 1GB, but {allow.max_size} was given.")
    return allow


def validate_project_storage_allow_patch(
    existing: models.ProjectStorageAllowDetail, body: apispec.ProjectStorageAllowPatch
) -> models.ProjectStorageAllowPatch:
    """Validate a patch of a project storage allow entry."""

    size = ByteSize.from_gibi(body.max_size) if body.max_size is not None else None
    if size and size < ByteSize.from_gibi(1):
        raise errors.ValidationError(message="The maximum size must be at least 1GB")
    return models.ProjectStorageAllowPatch(max_size=size)
