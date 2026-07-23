"""Business logic for Renku apps."""

from renku_data_services.renku_apps.models import App, AppRuntimeState, AppStatus
from renku_data_services.session.models import SessionLauncher


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

    if runtime.is_hibernated:
        return AppStatus.HIBERNATED
    if runtime.ready_status == "True":
        return AppStatus.READY
    if runtime.ready_status == "False":
        return AppStatus.FAILED
    return AppStatus.PENDING
