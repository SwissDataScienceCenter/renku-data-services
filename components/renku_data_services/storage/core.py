"""Business logic for project storage."""

from __future__ import annotations

from pathlib import PurePosixPath

from ulid import ULID

from renku_data_services import errors
from renku_data_services.base_models import RESET, ResetType
from renku_data_services.base_models.bytesize import ByteSize
from renku_data_services.storage import apispec, models


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


def validate_unsaved_project_storage_v2(body: apispec.ProjectStoragePost) -> models.UnsavedProjectStorageV2:
    """Validate a new project storage v2."""
    requested_size = ByteSize.from_gibi(body.requested_size)
    if requested_size < ByteSize.from_gibi(1):
        raise errors.ValidationError(message="The requested size must be at least 1GiB.")
    _validate_mount_path(body.mount_path)
    return models.UnsavedProjectStorageV2(
        project_id=ULID.from_str(body.project_id),
        storage_quota_id=ULID.from_str(body.storage_quota_id),
        requested_size_bytes=requested_size,
        mount_path=PurePosixPath(body.mount_path),
    )


def validate_project_storage_v2_patch(body: apispec.ProjectStoragePatch) -> models.ProjectStorageV2Patch:
    """Validate a patch of a project storage."""
    requested_size = ByteSize.from_gibi(body.requested_size) if body.requested_size is not None else None
    if requested_size is not None and requested_size < ByteSize.from_gibi(1):
        raise errors.ValidationError(message="The requested size must be at least 1GiB.")
    if body.mount_path:
        _validate_mount_path(body.mount_path)
    return models.ProjectStorageV2Patch(
        requested_size_bytes=requested_size,
        mount_path=PurePosixPath(body.mount_path) if body.mount_path else None,
    )


def validate_project_storage_v2_admin_patch(
    body: apispec.ProjectStorageAdminPatchV2,
) -> models.ProjectStorageV2AdminPatch:
    """Validate a patch of a project storage (unsafe, admin-only)."""
    project_id = ULID.from_str(body.project_id) if body.project_id else None
    storage_quota_id = ULID.from_str(body.storage_quota_id) if body.storage_quota_id else None
    k8s_pvc_name: str | ResetType | None
    match body.k8s_pvc_name:
        case None:
            k8s_pvc_name = None
        case "":
            k8s_pvc_name = RESET
        case _:
            k8s_pvc_name = body.k8s_pvc_name
    return models.ProjectStorageV2AdminPatch(
        project_id=project_id,
        storage_quota_id=storage_quota_id,
        k8s_pvc_name=k8s_pvc_name,
    )
