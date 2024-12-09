"""Constant values used for projects."""

from pathlib import PurePosixPath
from typing import Final

DEFAULT_SESSION_SECRETS_MOUNT_DIR_STR: Final[str] = "/secrets"
"""The default location where the secrets will be provided inside sessions, as a string."""

DEFAULT_SESSION_SECRETS_MOUNT_DIR: Final[PurePosixPath] = PurePosixPath(DEFAULT_SESSION_SECRETS_MOUNT_DIR_STR)
"""The default location where the secrets will be provided inside sessions."""
