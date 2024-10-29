"""Business logic for groups and namespaces."""

from renku_data_services.namespace import apispec, models


def validate_group_patch(patch: apispec.GroupPatchRequest) -> models.GroupPatch:
    """Validate the update to a group."""
    return models.GroupPatch(
        slug=patch.slug,
        name=patch.name,
        description=patch.description,
    )
