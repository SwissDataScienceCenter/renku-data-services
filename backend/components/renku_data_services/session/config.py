"""Configuration for session module."""

import os
from dataclasses import dataclass
from datetime import timedelta

from pydantic import ValidationError as PydanticValidationError

from renku_data_services.app_config import logging
from renku_data_services.session import crs as session_crs

logger = logging.getLogger(__name__)


@dataclass
class BuildsConfig:
    """Configuration for container image builds."""

    enabled: bool = False
    build_output_image_prefix: str | None = None
    vscodium_python_run_image: str | None = None
    build_strategy_name: str | None = None
    push_secret_name: str | None = None
    buildrun_retention_after_failed: timedelta | None = None
    buildrun_retention_after_succeeded: timedelta | None = None
    buildrun_build_timeout: timedelta | None = None
    node_selector: dict[str, str] | None = None
    tolerations: list[session_crs.Toleration] | None = None

    @classmethod
    def from_env(cls) -> "BuildsConfig":
        """Create a config from environment variables."""
        enabled = os.environ.get("IMAGE_BUILDERS_ENABLED", "false").lower() == "true"
        build_output_image_prefix = os.environ.get("BUILD_OUTPUT_IMAGE_PREFIX")
        vscodium_python_run_image = os.environ.get("BUILD_VSCODIUM_PYTHON_RUN_IMAGE")
        build_strategy_name = os.environ.get("BUILD_STRATEGY_NAME")
        push_secret_name = os.environ.get("BUILD_PUSH_SECRET_NAME")
        buildrun_retention_after_failed_seconds = int(os.environ.get("BUILD_RUN_RETENTION_AFTER_FAILED_SECONDS") or "0")
        buildrun_retention_after_failed = (
            timedelta(seconds=buildrun_retention_after_failed_seconds)
            if buildrun_retention_after_failed_seconds > 0
            else None
        )
        buildrun_retention_after_succeeded_seconds = int(
            os.environ.get("BUILD_RUN_RETENTION_AFTER_SUCCEEDED_SECONDS") or "0"
        )
        buildrun_retention_after_succeeded = (
            timedelta(seconds=buildrun_retention_after_succeeded_seconds)
            if buildrun_retention_after_succeeded_seconds > 0
            else None
        )
        buildrun_build_timeout_seconds = int(os.environ.get("BUILD_RUN_BUILD_TIMEOUT") or "0")
        buildrun_build_timeout = (
            timedelta(seconds=buildrun_build_timeout_seconds) if buildrun_build_timeout_seconds > 0 else None
        )

        if os.environ.get("DUMMY_STORES", "false").lower() == "true":
            enabled = True  # Enable image builds when running tests

        node_selector: dict[str, str] | None = None
        node_selector_str = os.environ.get("BUILD_NODE_SELECTOR")
        if node_selector_str:
            try:
                node_selector = session_crs.NodeSelector.model_validate_json(node_selector_str).root
            except PydanticValidationError:
                logger.error("Could not validate BUILD_NODE_SELECTOR. Will not use node selector for image builds.")

        tolerations: list[session_crs.Toleration] | None = None
        tolerations_str = os.environ.get("BUILD_NODE_TOLERATIONS")
        if tolerations_str:
            try:
                tolerations = session_crs.Tolerations.model_validate_json(tolerations_str).root
            except PydanticValidationError:
                logger.error("Could not validate BUILD_NODE_TOLERATIONS. Will not use tolerations for image builds.")

        return cls(
            enabled=enabled or False,
            build_output_image_prefix=build_output_image_prefix or None,
            vscodium_python_run_image=vscodium_python_run_image or None,
            build_strategy_name=build_strategy_name or None,
            push_secret_name=push_secret_name or None,
            buildrun_retention_after_failed=buildrun_retention_after_failed,
            buildrun_retention_after_succeeded=buildrun_retention_after_succeeded,
            buildrun_build_timeout=buildrun_build_timeout,
            node_selector=node_selector,
            tolerations=tolerations,
        )
