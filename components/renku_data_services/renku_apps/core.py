"""Business logic for Renku apps."""

from renku_data_services.renku_apps import models
from renku_data_services.renku_apps.crs import KnativeService
from renku_data_services.session.models import SessionLauncher


def knative_service_to_app(session_launcher: SessionLauncher, knative_service: KnativeService) -> models.App:
    """Convert a Knative service to an app."""

    app_service_url = knative_service.status.url if knative_service.status else None

    return models.App(
        name=knative_service.metadata.name,
        launcher_id=session_launcher.id,
        project_id=session_launcher.project_id,
        status=_project_app_status(knative_service),
        url=app_service_url,
        started=knative_service.started,
        image=knative_service.image,
    )


def _project_app_status(knative_service: KnativeService) -> models.AppStatus:
    """Convert a Knative service statuses to an app status."""
    if not knative_service.status or not knative_service.status.conditions:
        return models.AppStatus("pending")

    statuses = {condition.type: condition.status for condition in knative_service.status.conditions}
    status = statuses.get("Ready")

    if status == "True":
        return models.AppStatus("ready")
    if status == "False":
        return models.AppStatus("failed")

    return models.AppStatus("pending")
