"""Business logic for projects."""

from pathlib import PurePosixPath

from ulid import ULID

from renku_data_services import errors
from renku_data_services.authz.models import Visibility
from renku_data_services.project import apispec, models


def validate_project_patch(patch: apispec.ProjectPatch) -> models.ProjectPatch:
    """Validate the update to a project."""
    keywords = [kw.root for kw in patch.keywords] if patch.keywords is not None else None
    return models.ProjectPatch(
        name=patch.name,
        namespace=patch.namespace,
        visibility=Visibility(patch.visibility.value) if patch.visibility is not None else None,
        repositories=patch.repositories,
        description=patch.description,
        keywords=keywords,
    )


def validate_unsaved_session_secret_slot(
    body: apispec.SessionSecretSlotPost,
) -> models.UnsavedSessionSecretSlot:
    """Validate an unsaved secret slot."""
    _validate_session_launcher_secret_slot_filename(body.filename)
    return models.UnsavedSessionSecretSlot(
        project_id=ULID.from_str(body.project_id),
        name=body.name,
        description=body.description,
        filename=body.filename,
    )


def validate_session_secret_slot_patch(
    body: apispec.SessionSecretSlotPatch,
) -> models.SessionSecretSlotPatch:
    """Validate the update to a secret slot."""
    if body.filename is not None:
        _validate_session_launcher_secret_slot_filename(body.filename)
    return models.SessionSecretSlotPatch(
        name=body.name,
        description=body.description,
        filename=body.filename,
    )


def validate_session_secrets_patch(
    body: apispec.SessionSecretPatchList,
) -> list[models.SessionSecretPatchExistingSecret | models.SessionSecretPatchSecretValue]:
    """Validate the update to a session launcher's secrets."""
    result: list[models.SessionSecretPatchExistingSecret | models.SessionSecretPatchSecretValue] = []
    seen_slot_ids: set[str] = set()
    for item in body.root:
        if item.secret_slot_id in seen_slot_ids:
            raise errors.ValidationError(
                message=f"Found duplicate secret_slot_id '{item.secret_slot_id}' in the list of secrets."
            )
        seen_slot_ids.add(item.secret_slot_id)

        if isinstance(item, apispec.SessionSecretPatch2):
            result.append(
                models.SessionSecretPatchExistingSecret(
                    secret_slot_id=ULID.from_str(item.secret_slot_id),
                    secret_id=ULID.from_str(item.secret_id),
                )
            )
        else:
            result.append(
                models.SessionSecretPatchSecretValue(
                    secret_slot_id=ULID.from_str(item.secret_slot_id),
                    value=item.value,
                )
            )
    return result


def _validate_session_launcher_secret_slot_filename(filename: str) -> None:
    """Validate the filename field of a secret slot."""
    filename_candidate = PurePosixPath(filename)
    if filename_candidate.name != filename:
        raise errors.ValidationError(message=f"Filename {filename} is not valid.")
