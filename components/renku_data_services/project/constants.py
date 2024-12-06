"""Constant values used for projects."""

from pathlib import PurePosixPath

DEFAULT_SESSION_MOUNT_DIR_STR = "/secrets"
"""The default location where the secrets will be provided inside sessions, as a string."""

DEFAULT_SESSION_MOUNT_DIR = PurePosixPath(DEFAULT_SESSION_MOUNT_DIR_STR)
"""The default location where the secrets will be provided inside sessions."""
