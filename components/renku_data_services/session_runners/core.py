"""Business logic for session runners."""

from collections.abc import Sequence
from typing import Literal, cast

import jwt
import jwt.types
from ulid import ULID

from renku_data_services import base_models
from renku_data_services.app_config import logging
from renku_data_services.session_runners import apispec, models

logger = logging.getLogger(__name__)


def validate_unsaved_session_runner(runner: apispec.UserSessionRunnerPost) -> models.UnsavedUserSessionRunner:
    """Validate an unsaved user-scoped session runner."""
    return models.UnsavedUserSessionRunner(resource_pool_id=runner.resource_pool_id)


def validate_session_runner_patch(patch: apispec.UserSessionRunnerPatch) -> models.UserSessionRunnerPatch:
    """Validate the update to a user-scoped session runner."""
    status = models.RunnerStatus(patch.status.value)
    status = cast(Literal[models.RunnerStatus.ready] | Literal[models.RunnerStatus.not_ready], status)
    return models.UserSessionRunnerPatch(status=status)


def validate_patch_assigned_session_secrets(
    patch: apispec.RemoteUserSessionSecrets,
) -> Sequence[models.RemoteUserSessionSecret]:
    """Validate the update to secrets of a remote Renku session."""
    return [models.RemoteUserSessionSecret(name=item.name, value=item.value) for item in patch.root]


def get_runner_scope(user: base_models.APIUser) -> ULID | None:
    """Get the runner ID from the token's scope if applicable."""
    if user.access_token is None:
        return None
    claims = jwt.decode(
        user.access_token,
        options=jwt.types.Options(verify_signature=False),
    )
    scopes_str: str = claims.get("scope", "")
    scopes = scopes_str.split(" ")
    for scope in scopes:
        splits = scope.split(":", 1)
        if len(splits) == 2 and splits[0].lower() == "user_runner":
            try:
                runner_id: ULID = ULID.from_str(splits[1])
                logger.info(f"Parsed runner ID from scope: {str(runner_id)}.")
                return runner_id
            except ValueError:
                logger.error(f"Failed to parse runner ID from scope '{scope}': not a valid ULID.")
    return None
