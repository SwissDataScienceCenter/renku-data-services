"""Business logic for session runners."""

from typing import Literal, cast

from renku_data_services.session_runners import apispec, models


def validate_unsaved_session_runner(runner: apispec.SessionRunnerPost) -> models.UnsavedSessionRunner:
    """Validate an unsaved session runner."""
    return models.UnsavedSessionRunner(resource_pool_id=runner.resource_pool_id)


def validate_session_runner_contact_payload(
    payload: apispec.SessionRunnerContactPost,
) -> models.SessionRunnerContactPayload:
    """Validate the contact payload from a session runner."""
    status = models.RunnerStatus(payload.status.value)
    status = cast(Literal[models.RunnerStatus.ready] | Literal[models.RunnerStatus.not_ready], status)
    return models.SessionRunnerContactPayload(status=status)
