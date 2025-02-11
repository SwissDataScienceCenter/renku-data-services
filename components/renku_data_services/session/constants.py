"""Constants for sessions environments, session launchers and container image builds."""

from typing import Final

BUILD_OUTPUT_IMAGE_NAME: Final[str] = "renku-build"
"""The container image name created from Renku builds."""

BUILD_VSCODIUM_PYTHON_DEFAULT_RUN_IMAGE: Final[str] = "renku/renkulab-vscodium-python-runimage:ubuntu-c794f36"
"""The default run image for vscodium+python builds."""

BUILD_DEFAULT_BUILD_STRATEGY_NAME: Final[str] = "renku-buildpacks"
"""The name of the default build strategy."""

BUILD_DEFAULT_PUSH_SECRET_NAME: Final[str] = "renku-build-secret"
"""The name of the default secret to use when pushing Renku builds."""
