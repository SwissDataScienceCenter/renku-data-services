"""Business logic for sessions."""

from ulid import ULID

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


def validate_unsaved_session_launcher(launcher: apispec.SessionLauncherPost) -> models.UnsavedSessionLauncher:
    """Validate an unsaved session launcher."""
    return models.UnsavedSessionLauncher(
        project_id=ULID.from_str(launcher.project_id),
        name=launcher.name,
        description=launcher.description,
        environment_kind=launcher.environment_kind,
        environment_id=launcher.environment_id,
        resource_class_id=launcher.resource_class_id,
        container_image=launcher.container_image,
        default_url=launcher.default_url,
    )
