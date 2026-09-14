"""Configuration for project storage."""

from __future__ import annotations

import os
from dataclasses import dataclass

from renku_data_services.app_config import logging
from renku_data_services.base_models.bytesize import ByteSize
from renku_data_services.errors import errors

logger = logging.getLogger(__name__)


@dataclass
class ProjectStorageConfig:
    """The configuration for project storage."""

    enabled: bool
    storage_class: str
    """If set to "" then no storage class will be used and the PVC can bind only to a pre-existing PV."""
    maximum_size: ByteSize

    @classmethod
    def from_env(cls) -> ProjectStorageConfig:
        """Create a configuration from environment variables."""

        enabled = os.environ.get("PROJECT_STORAGE_ENABLED", "").lower() == "true"
        storage_class = os.environ.get("PROJECT_STORAGE_STORAGE_CLASS")
        maximum_size = os.environ.get("PROJECT_STORAGE_MAX_SIZE_GB") or "10"
        maximum_size = ByteSize.from_gibi(int(maximum_size))

        if enabled and not storage_class:
            raise errors.ConfigurationError(message="A storage_class is required for enabled project storage")

        return ProjectStorageConfig(enabled, storage_class=storage_class or "", maximum_size=maximum_size)
