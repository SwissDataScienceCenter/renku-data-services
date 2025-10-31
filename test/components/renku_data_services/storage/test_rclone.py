"""Tests for the rclone module."""

from renku_data_services.storage.rclone import RCloneValidator


def test_validate_switch_s3_no_endpoint() -> None:
    """Endpoint has a default value and is not required to specify."""
    validator = RCloneValidator()
    cfg = {"provider": "Switch", "type": "s3"}
    validator.validate(cfg, keep_sensitive=True)
