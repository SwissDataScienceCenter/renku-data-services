"""Constant values used for projects."""

from pathlib import PurePosixPath
from typing import Final

DEFAULT_SESSION_SECRETS_MOUNT_DIR_STR: Final[str] = "/secrets"
"""The default location where the secrets will be provided inside sessions, as a string."""

DEFAULT_SESSION_SECRETS_MOUNT_DIR: Final[PurePosixPath] = PurePosixPath(DEFAULT_SESSION_SECRETS_MOUNT_DIR_STR)
"""The default location where the secrets will be provided inside sessions."""

MIGRATION_ARGS: Final[list[str]] = [
    "jupyter server --ServerApp.ip=$RENKU_SESSION_IP "
    "--ServerApp.port=$RENKU_SESSION_PORT "
    "--ServerApp.allow_origin=* "
    "--ServerApp.base_url=$RENKU_BASE_URL_PATH "
    "--ServerApp.root_dir=$RENKU_WORKING_DIR "
    "--ServerApp.allow_remote_access=True "
    "--ContentsManager.allow_hidden=True "
    '--ServerApp.token="" '
    '--ServerApp.password=""'
]
"""The command-line arguments for migrating a v1 project."""

MIGRATION_COMMAND: Final[list[str]] = ["sh", "-c"]
"""The command to run for migrating the v1 project."""

MIGRATION_PORT: Final[int] = 8888
"""The port to use for migrating the v1 project."""

MIGRATION_WORKING_DIRECTORY: Final[str] = "/home/jovyan/work"
"""The working directory for migrating the v1 project."""

MIGRATION_MOUNT_DIRECTORY: Final[str] = "/home/jovyan/work"
"""The mount directory for migrating the v1 project."""

MIGRATION_UID: Final[int] = 1000
"""The UID for migrating the v1 project."""

MIGRATION_GID: Final[int] = 1000
"""The GID for migrating the v1 project."""
