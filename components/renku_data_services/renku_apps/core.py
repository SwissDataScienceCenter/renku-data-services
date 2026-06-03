"""Business logic for Renku apps."""

from renku_data_services.renku_apps.models import App, AppRuntimeState, AppStatus
from renku_data_services.session.models import SessionLauncher


def build_app(launcher: SessionLauncher, runtime: AppRuntimeState) -> App:
    """Compose an App from its launcher and the runtime state observed in the cluster."""
    return App(
        name=runtime.name,
        launcher_id=launcher.id,
        project_id=launcher.project_id,
        status=app_status_from_ready(runtime.ready_status),
        url=runtime.url,
        started=runtime.started_at,
        image=launcher.environment.container_image,
    )


def app_status_from_ready(ready_status: str | None) -> AppStatus:
    """Map a Kubernetes Ready-condition status value to an app status.

    Inputs follow the Kubernetes condition convention: "True", "False",
    "Unknown", or None when the condition is absent. Unknown and absent
    both collapse to PENDING.
    """
    if ready_status == "True":
        return AppStatus.READY
    if ready_status == "False":
        return AppStatus.FAILED
    return AppStatus.PENDING
