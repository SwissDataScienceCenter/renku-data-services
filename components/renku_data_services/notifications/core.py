"""Business logic for notifications."""

from renku_data_services.notifications import apispec, models


def validate_unsaved_alert(alert: apispec.AlertPost) -> models.UnsavedAlert:
    """Validate the creation of a new alert."""
    return models.UnsavedAlert(
        title=alert.title,
        message=alert.message,
        user_id=alert.user_id,
    )
