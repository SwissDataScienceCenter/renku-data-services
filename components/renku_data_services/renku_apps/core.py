"""Business logic for Renku apps."""

from datetime import datetime

from renku_data_services.project.models import Project
from renku_data_services.renku_apps import models
from renku_data_services.renku_apps.cr_knative_service import Condition
from renku_data_services.renku_apps.crs import KnativeService
from renku_data_services.session.models import SessionLauncher


def app_url(project: Project, base_domain: str) -> str:
    """Build the public URL for an app from its project path and the configured base domain."""
    return f"https://{project.slug}.{project.namespace.path.serialize()}.{base_domain}"


def knative_service_to_app(session_launcher: SessionLauncher, knative_service: KnativeService, url: str) -> models.App:
    """Convert a Knative service to an app."""
    return models.App(
        name=knative_service.metadata.name,
        launcher_id=session_launcher.id,
        project_id=session_launcher.project_id,
        status=_project_app_status(knative_service),
        url=url,
        started=_started_at(knative_service),
        image=session_launcher.environment.container_image,
    )


def _ready_condition(knative_service: KnativeService) -> Condition | None:
    """Get the Ready condition from a Knative service, or None if it doesn't exist."""
    if knative_service.status is None or not knative_service.status.conditions:
        return None
    return next((c for c in knative_service.status.conditions if c.type == "Ready"), None)


def _started_at(knative_service: KnativeService) -> datetime | None:
    """Get the time the Knative service became Ready, or None if not yet ready."""
    ready = _ready_condition(knative_service)
    if ready is None or ready.status != "True" or ready.lastTransitionTime is None:
        return None
    return datetime.fromisoformat(ready.lastTransitionTime)


def _project_app_status(knative_service: KnativeService) -> models.AppStatus:
    """Convert a Knative service's Ready condition into an app status."""
    ready = _ready_condition(knative_service)
    if ready is None:
        return models.AppStatus("pending")
    if ready.status == "True":
        return models.AppStatus("ready")
    if ready.status == "False":
        return models.AppStatus("failed")
    return models.AppStatus("pending")
