"""Business logic for projects."""

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
