"""Business logic for projects."""

from ulid import ULID

from renku_data_services.authz.models import Visibility
from renku_data_services.base_models import APIUser, Slug
from renku_data_services.data_connectors.db import DataConnectorProjectLinkRepository
from renku_data_services.errors import errors
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
    )


async def copy_project(
    project_id: ULID,
    user: APIUser,
    name: str,
    namespace: str,
    slug: str | None,
    description: str | None,
    repositories: list[models.Repository] | None,
    visibility: str | None,
    keywords: list[str],
    project_repo: ProjectRepository,
    session_repo: SessionRepository,
    data_connector_to_project_link_repo: DataConnectorProjectLinkRepository,
) -> tuple[models.Project, bool]:
    """Create a copy of a given project."""
    template = await project_repo.get_project(user=user, project_id=project_id)

    unsaved_project = models.UnsavedProject(
        name=name,
        namespace=namespace,
        slug=slug or Slug.from_name(name).value,
        description=description or template.description,
        repositories=repositories or template.repositories,
        created_by=user.id,  # type: ignore[arg-type]
        visibility=template.visibility if visibility is None else Visibility(visibility),
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
    copy_error = False
    dc_links = await data_connector_to_project_link_repo.get_links_to(user=user, project_id=project_id)
    for dc_link in dc_links:
        try:
            await data_connector_to_project_link_repo.copy_link(user=user, project_id=project.id, link=dc_link)
        except errors.MissingResourceError:
            copy_error = True

    return project, copy_error
