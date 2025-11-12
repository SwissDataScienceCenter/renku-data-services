"""Business logic for notifications."""

from renku_data_services import errors
from renku_data_services.notifications import apispec, models


def validate_unsaved_alert(alert: apispec.AlertPost) -> models.UnsavedAlert:
    """Validate the creation of a new alert."""
    return models.UnsavedAlert(
        title=alert.title,
        message=alert.message,
        user_id=alert.user_id,
        session_name=alert.session_name,
    )


def validate_alert_patch(patch: apispec.AlertPatch) -> models.AlertPatch:
    """Validate the patch for an update."""
    return models.AlertPatch(
        resolved=patch.resolved,
    )


def transform_alert_to_unsaved_alert(alert: apispec.AlertmanagerAlert) -> models.UnsavedAlert:
    """Transform a single Alertmanager alert to an UnsavedAlert."""

    labels = alert.labels
    annotations = alert.annotations

    user_id = labels.get("safe_username")
    if not user_id:
        raise errors.ValidationError(message="Alert is missing 'safe_username' label.")

    session_name = labels.get("statefulset")
    if not session_name:
        session_name = None

    title = annotations.get("title")
    if not title:
        raise errors.ValidationError(message="Alert is missing 'title' annotation.")

    message = annotations.get("description")
    if not message:
        raise errors.ValidationError(message="Alert is missing 'message' annotation.")

    return models.UnsavedAlert(
        title=title,
        message=message,
        user_id=user_id,
        session_name=session_name,
    )


def transform_alertmanager_webhook(
    webhook: apispec.AlertmanagerWebhook,
) -> tuple[list[models.UnsavedAlert], list[models.UnsavedAlert]]:
    """Transform Alertmanager webhook payload to a tuple of firing and resolved UnsavedAlerts."""

    firing_alerts: list[models.UnsavedAlert] = []
    resolved_alerts: list[models.UnsavedAlert] = []

    for alert in webhook.alerts:
        unsaved_alert = transform_alert_to_unsaved_alert(alert)

        if alert.status == "firing":
            firing_alerts.append(unsaved_alert)
        elif alert.status == "resolved":
            resolved_alerts.append(unsaved_alert)

    return firing_alerts, resolved_alerts
