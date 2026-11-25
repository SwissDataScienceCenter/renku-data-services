"""Constant values used for resource pools and resource classes."""

from typing import Final

from renku_data_services.crc import models

DEFAULT_RUNTIME_PLATFORM: Final[models.RuntimePlatform] = models.RuntimePlatform.linux_amd64
"""The default runtime platform used by resource pools, "linux/amd64"."""

SESSION_PRIORITY_VALUE: Final[int] = 100
"""The priority of sessions and jobs in a resource pool with a quota."""

PREEMPTIBLE_PRIORITY_VALUE: Final[int] = -5
"""The priority of sessions and jobs in a preemptible resource class."""
