"""Business logic for projects."""

from pathlib import PurePosixPath

from ulid import ULID

from renku_data_services import errors
from renku_data_services.authz.models import Visibility
from renku_data_services.base_models import RESET, APIUser, Slug
from renku_data_services.data_connectors.db import DataConnectorProjectLinkRepository
from renku_data_services.project import apispec, models
from renku_data_services.project.db import ProjectRepository
from renku_data_services.session.db import SessionRepository


def validate_unsaved_project(body: apispec.ProjectPost, created_by: str) -> models.UnsavedProject:
    """Validate an unsaved project."""
    keywords = [kw.root for kw in body.keywords] if body.keywords is not None else []
    visibility = Visibility.PRIVATE if body.visibility is None else Visibility(body.visibility.value)
    secrets_mount_directory = PurePosixPath(body.secrets_mount_directory) if body.secrets_mount_directory else None
    if secrets_mount_directory is not None and not secrets_mount_directory.is_absolute():
        secrets_mount_directory = PurePosixPath("/") / secrets_mount_directory
    return models.UnsavedProject(
        name=body.name,
        namespace=body.namespace,
        slug=body.slug or Slug.from_name(body.name).value,
        description=body.description,
        repositories=body.repositories or [],
        created_by=created_by,
        visibility=visibility,
        keywords=keywords,
        documentation=body.documentation,
        secrets_mount_directory=secrets_mount_directory,
    )


def validate_project_patch(patch: apispec.ProjectPatch) -> models.ProjectPatch:
    """Validate the update to a project."""
    keywords = [kw.root for kw in patch.keywords] if patch.keywords is not None else None
    secrets_mount_directory = (
        PurePosixPath(patch.secrets_mount_directory)
        if patch.secrets_mount_directory
        else RESET
        if patch.secrets_mount_directory == ""
        else None
    )
    if isinstance(secrets_mount_directory, PurePosixPath) and not secrets_mount_directory.is_absolute():
        secrets_mount_directory = PurePosixPath("/") / secrets_mount_directory
    return models.ProjectPatch(
        name=patch.name,
        namespace=patch.namespace,
        visibility=Visibility(patch.visibility.value) if patch.visibility is not None else None,
        repositories=patch.repositories,
        description=patch.description,
        keywords=keywords,
        documentation=patch.documentation,
        template_id=None if patch.template_id is None else "",
        is_template=patch.is_template,
        secrets_mount_directory=secrets_mount_directory,
    )


async def copy_project(
    project_id: ULID,
    user: APIUser,
    name: str,
    namespace: str,
    slug: str | None,
    description: str | None,
    repositories: list[models.Repository] | None,
    visibility: Visibility | None,
    keywords: list[str],
    secrets_mount_directory: str | None,
    project_repo: ProjectRepository,
    session_repo: SessionRepository,
    data_connector_to_project_link_repo: DataConnectorProjectLinkRepository,
) -> models.Project:
    """Create a copy of a given project."""
    template = await project_repo.get_project(user=user, project_id=project_id)

    unsaved_project = models.UnsavedProject(
        name=name,
        namespace=namespace,
        slug=slug or Slug.from_name(name).value,
        description=description or template.description,
        repositories=repositories or template.repositories,
        created_by=user.id,  # type: ignore[arg-type]
        visibility=template.visibility if visibility is None else visibility,
        keywords=keywords or template.keywords,
        template_id=template.id,
        secrets_mount_directory=PurePosixPath(secrets_mount_directory) if secrets_mount_directory else None,
    )
    project = await project_repo.insert_project(user, unsaved_project)

    # NOTE: Copy session launchers
    launchers = await session_repo.get_project_launchers(user=user, project_id=project_id)
    for launcher in launchers:
        await session_repo.copy_launcher(user=user, project_id=project.id, launcher=launcher)

    # NOTE: Copy data connector links. If this operation fails due to lack of permission, still proceed to create the
    # copy but return an error code that reflects this
    copy_error = False
    dc_links = await data_connector_to_project_link_repo.get_links_to(user=user, project_id=project_id)
    for dc_link in dc_links:
        try:
            await data_connector_to_project_link_repo.copy_link(user=user, project_id=project.id, link=dc_link)
        except errors.MissingResourceError:
            copy_error = True

    if copy_error:
        raise errors.CopyDataConnectorsError()

    return project


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
