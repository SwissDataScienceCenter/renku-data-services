"""Business logic for session runners."""

from typing import Literal, cast

from renku_data_services.session_runners import apispec, models


def validate_unsaved_session_runner(runner: apispec.UserSessionRunnerPost) -> models.UnsavedUserSessionRunner:
    """Validate an unsaved user-scoped session runner."""
    return models.UnsavedUserSessionRunner(resource_pool_id=runner.resource_pool_id)


def validate_session_runner_patch(patch: apispec.UserSessionRunnerPatch) -> models.UserSessionRunnerPatch:
    """Validate the update to a user-scoped session runner."""
    status = models.RunnerStatus(patch.status.value)
    status = cast(Literal[models.RunnerStatus.ready] | Literal[models.RunnerStatus.not_ready], status)
    return models.UserSessionRunnerPatch(status=status)


# def validate_patch_assigned_session_secrets(
#     patch: apispec.AssignedSessionSecrets,
# ) -> Sequence[models.AssignedSessionSecret]:
#     """Validate the update to secrets of a session assigned to a runner."""
#     return [models.AssignedSessionSecret(name=item.name, value=item.value) for item in patch.root]
