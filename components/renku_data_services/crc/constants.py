"""Constant values used for resource pools and resource classes."""

from typing import Final

from renku_data_services.crc import models

DEFAULT_RUNTIME_PLATFORM: Final[models.RuntimePlatform] = models.RuntimePlatform.linux_amd64
"""The default runtime platform used by resource pools, "linux/amd64"."""
