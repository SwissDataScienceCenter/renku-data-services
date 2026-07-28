"""Business logic for Renku apps."""

import re
from typing import Final

from ulid import ULID

from renku_data_services.renku_apps.models import App, AppRuntimeState, AppStatus
from renku_data_services.session.models import SessionLauncher

_TERMINAL_READY_REASONS = frozenset({"ProgressDeadlineExceeded", "RevisionFailed"})
"""Knative Ready=False reasons that mean the revision has definitively failed (others are transient)."""

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


def build_app(launcher: SessionLauncher, runtime: AppRuntimeState) -> App:
    """Compose an App from its launcher and the runtime state observed in the cluster."""
    return App(
        name=runtime.name,
        launcher_id=launcher.id,
        project_id=launcher.project_id,
        status=derive_app_status(runtime),
        url=runtime.url,
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
