"""Constants for sessions environments, session launchers and container image builds."""

import re
from datetime import timedelta
from pathlib import PurePosixPath
from re import Pattern
from typing import Final

from renku_data_services.k8s.models import GVK

BUILD_DEFAULT_OUTPUT_IMAGE_PREFIX: Final[str] = "harbor.dev.renku.ch/renku-builds/"
"""The default container image prefix for Renku builds."""

BUILD_OUTPUT_IMAGE_NAME: Final[str] = "renku-build"
"""The container image name created from Renku builds."""

BUILD_BUILDER_IMAGE: Final[str] = "ghcr.io/swissdatasciencecenter/renku-frontend-buildpacks/selector:0.1.0"

BUILD_RUN_IMAGE: Final[str] = "ghcr.io/swissdatasciencecenter/renku-frontend-buildpacks/base-image:0.1.0"
BUILD_MOUNT_DIRECTORY: Final[PurePosixPath] = PurePosixPath("/home/renku/work")
BUILD_WORKING_DIRECTORY: Final[PurePosixPath] = BUILD_MOUNT_DIRECTORY
BUILD_UID: Final[int] = 1000
BUILD_GID: Final[int] = 1000
BUILD_PORT: Final[int] = 8888
DEFAULT_URLS: Final[dict[str, str]] = {
    "vscodium": "/",
    "jupyterlab": "/lab",
}

BUILD_DEFAULT_BUILD_STRATEGY_NAME: Final[str] = "renku-buildpacks-v2"
"""The name of the default build strategy."""

BUILD_DEFAULT_PUSH_SECRET_NAME: Final[str] = "renku-build-secret"
"""The name of the default secret to use when pushing Renku builds."""

BUILD_RUN_DEFAULT_RETENTION_AFTER_FAILED: Final[timedelta] = timedelta(minutes=5)
"""The default retention TTL for BuildRuns when in failed state."""

BUILD_RUN_DEFAULT_RETENTION_AFTER_SUCCEEDED: Final[timedelta] = timedelta(minutes=5)
"""The default retention TTL for BuildRuns when in succeeded state."""

BUILD_RUN_DEFAULT_TIMEOUT: Final[timedelta] = timedelta(hours=1)
"""The default timeout for build after which they get cancelled."""

BUILD_RUN_GVK: Final[GVK] = GVK(group="shipwright.io", version="v1beta1", kind="BuildRun")

TASK_RUN_GVK: Final[GVK] = GVK(group="tekton.dev", version="v1", kind="TaskRun")

DUMMY_TASK_RUN_USER_ID: Final[str] = "DummyTaskRunUser"
"""The user id to use for TaskRuns in the k8s cache.

Note: we can't curently propagate labels to TaskRuns through shipwright, so we just use a dummy user id for all of them.
This might change if shipwright SHIP-0034 gets implemented.
"""

# see https://pubs.opengroup.org/onlinepubs/9699919799/basedefs/V1_chap03.html#tag_03_235
ENV_VARIABLE_REGEX: Final[str] = r"^[a-zA-Z_][a-zA-Z0-9_]*$"
"""The regex to validate environment variable names.
see Name at https://pubs.opengroup.org/onlinepubs/9699919799/basedefs/V1_chap03.html#tag_03_235
"""

ENV_VARIABLE_NAME_MATCHER: Final[Pattern[str]] = re.compile(ENV_VARIABLE_REGEX)
"""The compiled regex to validate environment variable names."""
