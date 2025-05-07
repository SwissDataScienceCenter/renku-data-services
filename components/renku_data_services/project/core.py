"""Business logic for projects."""

from pathlib import PurePosixPath
from typing import cast
from urllib.parse import urljoin, urlparse

import httpx
from ulid import ULID

from renku_data_services import errors
from renku_data_services.authz.models import Visibility
from renku_data_services.base_models import RESET, APIUser, ResetType, Slug
from renku_data_services.base_models.core import GitlabAPIProtocol
from renku_data_services.data_connectors.db import DataConnectorRepository
from renku_data_services.project import apispec, models
from renku_data_services.project.db import ProjectRepository
from renku_data_services.session.db import SessionRepository


def validate_unsaved_project(body: apispec.ProjectPost, created_by: str) -> models.UnsavedProject:
    """Validate an unsaved project."""
    keywords = [kw.root for kw in body.keywords] if body.keywords is not None else []
    visibility = Visibility.PRIVATE if body.visibility is None else Visibility(body.visibility.value)
    secrets_mount_directory = PurePosixPath(body.secrets_mount_directory) if body.secrets_mount_directory else None
    repositories = _validate_repositories(body.repositories)
    return models.UnsavedProject(
        name=body.name,
        namespace=body.namespace,
        slug=body.slug or Slug.from_name(body.name).value,
        description=body.description,
        repositories=repositories or [],
        created_by=created_by,
        visibility=visibility,
        keywords=keywords,
        documentation=body.documentation,
        secrets_mount_directory=secrets_mount_directory,
    )


def validate_project_patch(patch: apispec.ProjectPatch) -> models.ProjectPatch:
    """Validate the update to a project."""
    keywords = [kw.root for kw in patch.keywords] if patch.keywords is not None else None
    secrets_mount_directory: PurePosixPath | ResetType | None
    match patch.secrets_mount_directory:
        case "":
            secrets_mount_directory = RESET
        case str():
            secrets_mount_directory = PurePosixPath(patch.secrets_mount_directory)
        case _:
            secrets_mount_directory = None
    repositories = _validate_repositories(patch.repositories)
    return models.ProjectPatch(
        name=patch.name,
        namespace=patch.namespace,
        slug=patch.slug,
        visibility=Visibility(patch.visibility.value) if patch.visibility is not None else None,
        repositories=repositories,
        description=patch.description,
        keywords=keywords,
        documentation=patch.documentation,
        template_id=None if patch.template_id is None else "",
        is_template=patch.is_template,
        secrets_mount_directory=secrets_mount_directory,
    )


async def copy_project(
    source_project_id: ULID,
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
    data_connector_repo: DataConnectorRepository,
) -> models.Project:
    """Create a copy of a given project."""
    template = await project_repo.get_project(user=user, project_id=source_project_id, with_documentation=True)
    repositories_ = _validate_repositories(repositories)

    unsaved_project = models.UnsavedProject(
        name=name,
        namespace=namespace,
        slug=slug or Slug.from_name(name).value,
        description=description or template.description,
        repositories=repositories_ or template.repositories,
        created_by=user.id,  # type: ignore[arg-type]
        visibility=template.visibility if visibility is None else visibility,
        keywords=keywords or template.keywords,
        template_id=template.id,
        secrets_mount_directory=PurePosixPath(secrets_mount_directory) if secrets_mount_directory else None,
        documentation=template.documentation,
    )
    project = await project_repo.insert_project(user, unsaved_project)

    # NOTE: Copy session launchers
    launchers = await session_repo.get_project_launchers(user=user, project_id=source_project_id)
    for launcher in launchers:
        await session_repo.copy_launcher(user=user, project_id=project.id, launcher=launcher)

    # NOTE: Copy data connector links. If this operation fails due to lack of permission, still proceed to create the
    # copy but return an error code that reflects this
    uncopied_dc_ids: list[ULID] = []
    dc_links = await data_connector_repo.get_links_to(user=user, project_id=source_project_id)
    for dc_link in dc_links:
        try:
            await data_connector_repo.copy_link(user=user, target_project_id=project.id, link=dc_link)
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


def _validate_repositories(repositories: list[str] | None) -> list[str] | None:
    """Validate a list of git repositories."""
    if repositories is None:
        return None
    seen: set[str] = set()
    without_duplicates: list[str] = []
    for repo in repositories:
        repo = _validate_repository(repo)
        if repo not in seen:
            without_duplicates.append(repo)
            seen.add(repo)
    return without_duplicates


def _validate_repository(repository: str) -> str:
    """Validate a git repository."""
    stripped = repository.strip()
    parsed = urlparse(stripped)
    if parsed.scheme not in ["http", "https"]:
        raise errors.ValidationError(message=f'The repository URL "{repository}" is not a valid HTTP or HTTPS URL.')
    return stripped


def _validate_session_launcher_secret_slot_filename(filename: str) -> None:
    """Validate the filename field of a secret slot."""
    filename_candidate = PurePosixPath(filename)
    if filename_candidate.name != filename:
        raise errors.ValidationError(message=f"Filename {filename} is not valid.")


async def get_v1_project_info(
    user: APIUser,
    internal_gitlab_user: APIUser,
    project_path: str,
    gitlab_client: GitlabAPIProtocol,
    core_svc_url: str,
) -> dict[str, str | list[str] | int | None]:
    """Request project information from the core service for a Renku v1 project."""
    url = await gitlab_client.get_project_url_from_path(internal_gitlab_user, project_path)
    if not url:
        raise errors.MissingResourceError(
            message=f"The Renku v1 project with path {project_path} cannot be found "
            "in Gitlab or you do not have access to it"
        )

    body = {"git_url": url, "is_delayed": False, "migrate_project": False}
    headers = {}
    if user.access_token:
        headers["Authorization"] = user.access_token
    full_url = urljoin(core_svc_url + "/", "project.show")
    async with httpx.AsyncClient() as clnt:
        res = await clnt.post(full_url, json=body, headers=headers)
    if res.status_code != 200:
        raise errors.MissingResourceError(
            message=f"The core service responded with an unexpected code {res.status_code} when getting "
            f"information about project {project_path} and url {url}"
        )
    res_json = cast(dict[str, dict[str, str | int | list[str]]], res.json())
    if res_json.get("error") is not None:
        raise errors.MissingResourceError(
            message=f"The core service responded with an error when getting "
            f"information about project {project_path} and url {url}",
            detail=cast(str | None, res_json.get("error", {}).get("userMessage")),
        )

    kws = res_json.get("result", {}).get("keywords")
    desc = res_json.get("result", {}).get("description")
    id = res_json.get("result", {}).get("id")
    name = res_json.get("result", {}).get("name")
    output = {
        "name": name,
        "id": id,
        "keywords": kws,
        "description": desc,
    }
    return output
