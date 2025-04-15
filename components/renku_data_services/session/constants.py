"""Constants for sessions environments, session launchers and container image builds."""

from datetime import timedelta
from typing import Final

BUILD_DEFAULT_OUTPUT_IMAGE_PREFIX: Final[str] = "harbor.dev.renku.ch/renku-builds/"
"""The default container image prefix for Renku builds."""

BUILD_OUTPUT_IMAGE_NAME: Final[str] = "renku-build"
"""The container image name created from Renku builds."""

BUILD_BUILDER_IMAGE: Final[str] = "olevski90/selector:0.0.1-test3"

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
