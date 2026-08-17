"""Business logic for Renku apps."""

import re
from typing import Final

from ulid import ULID

from renku_data_services import base_models, errors
from renku_data_services.app_config import logging
from renku_data_services.authz.models import Visibility
from renku_data_services.data_connectors.db import DataConnectorSecretRepository
from renku_data_services.data_connectors.models import (
    DataConnector,
    DataConnectorWithSecrets,
    GlobalDataConnector,
)
from renku_data_services.k8s.constants import DUMMY_RENKU_APP_USER_ID
from renku_data_services.renku_apps.models import App, AppRuntimeState, AppStatus
from renku_data_services.session.models import SessionLauncher
from renku_data_services.storage.rclone import RCloneValidator

logger = logging.getLogger(__name__)

_TERMINAL_READY_REASONS = frozenset({"ProgressDeadlineExceeded", "RevisionFailed"})
"""Knative Ready=False reasons that mean the revision has definitively failed (others are transient)."""

_OAUTH2_INTEGRATION_STORAGE_TYPES = frozenset({"drive", "dropbox"})
"""rclone storage types whose credentials come from an OAuth2 integration.

SECURITY: this is the app-side copy of the drive/dropbox -> provider mapping that
``notebooks.data_sources.DataSourceRepository`` uses for sessions. If a new OAuth-backed
storage type is added there, it must be added here too -- otherwise a private connector of
that type would clear this filter and be mounted into an anonymous public app.
"""

APP_NAME_MAX_LENGTH: Final[int] = 50
"""Upper bound on a generated app name; must match AppName.maxLength in api.spec.yaml."""

_LAUNCHER_ID_SUFFIX_LENGTH: Final[int] = 8
"""Trailing characters of the launcher ULID that make an app name unique per launcher."""

_SLUG_MAX_LENGTH: Final[int] = APP_NAME_MAX_LENGTH - _LAUNCHER_ID_SUFFIX_LENGTH - 1


def generate_app_name(project_slug: str, launcher_id: ULID) -> str:
    """Generate a DNS-1035 label name for an app, bounded to APP_NAME_MAX_LENGTH."""
    suffix = str(launcher_id)[-_LAUNCHER_ID_SUFFIX_LENGTH:].lower()
    return f"{_slug_label(project_slug)}-{suffix}"


def _slug_label(slug: str) -> str:
    """Coerce a project slug (which may hold dots, underscores or a leading digit) into a DNS-1035 label."""
    label = re.sub(r"-+", "-", re.sub(r"[^a-z0-9]", "-", slug.lower()))
    if not label[:1].isalpha():
        label = f"app-{label}"
    return label[:_SLUG_MAX_LENGTH].rstrip("-")


def app_url(base_url: str | None, default_url: str) -> str | None:
    """Join the URL Knative assigned to the service with the environment's default URL."""
    if base_url is None:
        return None
    path = default_url.strip()
    if not path or path == "/":
        return base_url
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def build_app(launcher: SessionLauncher, runtime: AppRuntimeState) -> App:
    """Compose an App from its launcher and the runtime state observed in the cluster."""
    return App(
        name=runtime.name,
        launcher_id=launcher.id,
        project_id=launcher.project_id,
        status=derive_app_status(runtime),
        url=app_url(runtime.url, launcher.environment.default_url),
        started=runtime.started_at,
        image=runtime.image,
    )


def derive_app_status(runtime: AppRuntimeState) -> AppStatus:
    """Derive an app status from the runtime state."""

    if runtime.ready_status == "True":
        return AppStatus.READY
    if runtime.ready_status == "False" and runtime.ready_reason in _TERMINAL_READY_REASONS:
        return AppStatus.FAILED
    return AppStatus.PENDING


def is_app_mountable(dc: DataConnector | GlobalDataConnector, validator: RCloneValidator) -> bool:
    """Return whether a data connector is safe to mount into a public, anonymous app.

    A connector qualifies only if it is public, needs no static credentials, and needs no
    OAuth integration. Both credential checks matter: OAuth connectors have no static
    private fields, so without the OAuth check a user's private Drive would leak into an
    anonymous app. An unusable rclone configuration excludes the connector rather than
    failing the launch.
    """
    try:
        has_private_fields = bool(list(validator.get_private_fields(dc.storage.configuration)))
    except errors.ValidationError:
        logger.warning("Excluding data connector %s from app: unusable rclone configuration", dc.id, exc_info=True)
        return False
    return (
        dc.visibility == Visibility.PUBLIC
        and not has_private_fields
        and dc.storage.configuration.get("type") not in _OAUTH2_INTEGRATION_STORAGE_TYPES
    )


async def select_mountable_connectors(
    project_id: ULID,
    dc_secret_repo: DataConnectorSecretRepository,
    validator: RCloneValidator,
) -> list[DataConnectorWithSecrets]:
    """Enumerate the project's linked connectors and keep only those safe for an app.

    Enumeration always runs as the anonymous app identity (``DUMMY_RENKU_APP_USER_ID``):
    the authz layer then only returns publicly-readable connectors, and downstream config
    resolution mints no user tokens -- the same property that makes anonymous sessions
    safe. Passing a real user here would defeat that, so the identity is not a parameter.
    It reuses the project-membership model sessions use (``DataConnectorToProjectLinkORM``);
    there is no app-specific connector list.
    """
    app_user = base_models.AnonymousAPIUser(id=DUMMY_RENKU_APP_USER_ID)
    survivors: list[DataConnectorWithSecrets] = []
    async for dc in dc_secret_repo.get_data_connectors_with_secrets(app_user, project_id):
        if is_app_mountable(dc.data_connector, validator):
            survivors.append(dc)

    logger.info(
        "Selected %d data connector(s) to mount for project %s",
        len(survivors),
        project_id,
    )
    return survivors
