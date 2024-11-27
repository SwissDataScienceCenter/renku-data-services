"""Business logic for projects."""

from pathlib import PurePosixPath

from ulid import ULID

from renku_data_services import errors
from renku_data_services.authz.models import Visibility
from renku_data_services.base_models import APIUser, Slug
from renku_data_services.data_connectors.db import DataConnectorProjectLinkRepository, DataConnectorRepository
from renku_data_services.project import apispec, models
from renku_data_services.project.db import ProjectRepository
from renku_data_services.session.db import SessionRepository


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
        documentation=patch.documentation,
        template_id=None if patch.template_id is None else "",
        is_template=patch.is_template,
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
    project_repo: ProjectRepository,
    session_repo: SessionRepository,
    data_connector_to_project_link_repo: DataConnectorProjectLinkRepository,
    data_connector_repo: DataConnectorRepository,
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
    )
    project = await project_repo.insert_project(user, unsaved_project)

    # NOTE: Copy session launchers
    launchers = await session_repo.get_project_launchers(user=user, project_id=project_id)
    for launcher in launchers:
        await session_repo.copy_launcher(user=user, project_id=project.id, launcher=launcher)

    # NOTE: Copy data connector links. If this operation fails due to lack of permission, still proceed to create the
    # copy but return an error code that reflects this
    uncopied_dc_ids: list[ULID] = []
    dc_links = await data_connector_to_project_link_repo.get_links_to(user=user, project_id=project_id)
    for dc_link in dc_links:
        try:
            await data_connector_to_project_link_repo.copy_link(user=user, project_id=project.id, link=dc_link)
        except errors.MissingResourceError:
            uncopied_dc_ids.append(dc_link.data_connector_id)

    if uncopied_dc_ids:
        data_connectors_names_ids = await data_connector_repo.get_data_connectors_names_and_ids(user, uncopied_dc_ids)
        dc_str = ", ".join([f"{name} ({id})" for name, id in data_connectors_names_ids])
        if len(data_connectors_names_ids) == 1:
            message = (
                f"The project was copied but data connector with name '{dc_str}' was not able to be linked to "
                "your copy of this project due to insufficient permissions. To make a copy that includes the data "
                "connector, ask its owner to make it public."
            )
        else:
            message = (
                f"The project was copied but data connectors with names '[{dc_str}]' were not able to be linked to "
                "your copy of this project due to insufficient permissions. To make a copy that includes the data "
                "connectors, ask their owners to make them public."
            )
        raise errors.CopyDataConnectorsError(message=message)

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


def _validate_session_launcher_secret_slot_filename(filename: str) -> None:
    """Validate the filename field of a secret slot."""
    filename_candidate = PurePosixPath(filename)
    if filename_candidate.name != filename:
        raise errors.ValidationError(message=f"Filename {filename} is not valid.")
