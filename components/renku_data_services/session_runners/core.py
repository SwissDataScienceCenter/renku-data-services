"""Business logic for session runners."""

from renku_data_services.session_runners import apispec, models


def validate_unsaved_session_runner(runner: apispec.SessionRunnerPost) -> models.UnsavedSessionRunner:
    """Validate an unsaved session runner."""
    return models.UnsavedSessionRunner(resource_pool_id=runner.resource_pool_id)
