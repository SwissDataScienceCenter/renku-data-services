"""Business logic for sessions."""

from renku_data_services.session import apispec, models


def validate_unsaved_environment(environment: apispec.EnvironmentPost) -> models.UnsavedEnvironment:
    """Validate an unsaved session environment."""
    return models.UnsavedEnvironment(
        name=environment.name,
        description=environment.description,
        container_image=environment.container_image,
        default_url=environment.default_url,
    )


def validate_environment_patch(patch: apispec.EnvironmentPatch) -> models.EnvironmentPatch:
    """Validate the update to a session environment."""
    return models.EnvironmentPatch(
        name=patch.name,
        description=patch.description,
        container_image=patch.container_image,
        default_url=patch.default_url,
    )
