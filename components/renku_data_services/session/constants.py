"""Constants for sessions environments, session launchers and container image builds."""

import re
from datetime import timedelta
from re import Pattern
from typing import Final

BUILD_DEFAULT_OUTPUT_IMAGE_PREFIX: Final[str] = "harbor.dev.renku.ch/renku-builds/"
"""The default container image prefix for Renku builds."""

BUILD_OUTPUT_IMAGE_NAME: Final[str] = "renku-build"
"""The container image name created from Renku builds."""

BUILD_VSCODIUM_PYTHON_DEFAULT_RUN_IMAGE: Final[str] = "renku/renkulab-vscodium-python-runimage:ubuntu-c794f36"
"""The default run image for vscodium+python builds."""

BUILD_DEFAULT_BUILD_STRATEGY_NAME: Final[str] = "renku-buildpacks"
"""The name of the default build strategy."""

BUILD_DEFAULT_PUSH_SECRET_NAME: Final[str] = "renku-build-secret"
"""The name of the default secret to use when pushing Renku builds."""

BUILD_RUN_DEFAULT_RETENTION_AFTER_FAILED: Final[timedelta] = timedelta(minutes=5)
"""The default retention TTL for BuildRuns when in failed state."""

BUILD_RUN_DEFAULT_RETENTION_AFTER_SUCCEEDED: Final[timedelta] = timedelta(minutes=5)
"""The default retention TTL for BuildRuns when in succeeded state."""

BUILD_RUN_DEFAULT_TIMEOUT: Final[timedelta] = timedelta(hours=1)
"""The default timeout for build after which they get cancelled."""

BUILD_RUN_KIND: Final[str] = "BuildRun"
"""K8s kind of build runs."""

BUILD_RUN_VERSION: Final[str] = "shipwright.io/v1beta1"
"""K8s version of build runs."""

TASK_RUN_KIND: Final[str] = "TaskRun"
"""K8s kind of task runs."""

TASK_RUN_VERSION: Final[str] = "tekton.dev/v1"
"""K8s version of task runs."""

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
