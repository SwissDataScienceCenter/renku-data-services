"""Business logic for notifications."""

import logging

from renku_data_services.notifications import apispec, models

logger = logging.getLogger(__name__)


def validate_unsaved_alert(alert: apispec.AlertPost) -> models.UnsavedAlert:
    """Validate the creation of a new alert."""
    return models.UnsavedAlert(
        title=alert.title,
        message=alert.message,
        event_type=alert.event_type,
        user_id=alert.user_id,
        session_name=alert.session_name,
    )


def validate_alert_patch(patch: apispec.AlertPatch) -> models.AlertPatch:
    """Validate the patch for an update."""
    return models.AlertPatch(
        resolved=patch.resolved,
    )


def transform_alert_to_unsaved_alert(alert: apispec.AlertmanagerAlert) -> models.UnsavedAlert | None:
    """Transform a single Alertmanager alert to an UnsavedAlert."""
    labels = alert.labels
    annotations = alert.annotations

    user_id = labels.get("safe_username")
    if not user_id:
        logger.warning("Alert is missing 'safe_username' label, skipping: %s", alert)
        return None

    session_name = labels.get("statefulset")
    if not session_name:
        # We discard alerts without a session for now
        return None

    title = annotations.get("title")
    if not title:
        logger.warning("Alert is missing 'title' annotation, skipping: %s", alert)
        return None

    message = annotations.get("description")
    if not message:
        logger.warning("Alert is missing 'description' annotation, skipping: %s", alert)
        return None

    event_type = labels.get("alertname")
    if not event_type:
        logger.warning("Alert is missing 'alertname' label, skipping: %s", alert)
        return None

    return models.UnsavedAlert(
        title=title,
        message=message,
        event_type=event_type,
        user_id=user_id,
        session_name=session_name,
    )


def alertmanager_webhook_to_unsaved_alerts(
    webhook: apispec.AlertmanagerWebhook,
) -> tuple[list[models.UnsavedAlert], list[models.UnsavedAlert]]:
    """Transform Alertmanager webhook payload to a tuple of firing and resolved UnsavedAlerts."""

    firing_alerts: list[models.UnsavedAlert] = []
    resolved_alerts: list[models.UnsavedAlert] = []

    for alert in webhook.alerts:
        unsaved_alert = transform_alert_to_unsaved_alert(alert)

        if unsaved_alert is None:
            continue

        if alert.status == apispec.Status.firing:
            firing_alerts.append(unsaved_alert)
        elif alert.status == apispec.Status.resolved:
            resolved_alerts.append(unsaved_alert)

    return firing_alerts, resolved_alerts
