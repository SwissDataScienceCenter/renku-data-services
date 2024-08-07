"""Secret schemas."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from marshmallow import Schema, ValidationError, fields
from ulid import ULID

BLACKLISTED_PATHS = ["bin", "sbin", "usr", "dev", "proc", "sys", "lib", "var"]


class PathField(fields.Field):
    """Custom field spec for a file path."""

    def _serialize(self, value: Any, attr: str | None, obj: Any, **kwargs: dict) -> str:
        if value is None:
            return ""
        return str(value)

    def _deserialize(self, value: Any, attr: str | None, data: Any, **kwargs: dict) -> str:
        path = Path(value)
        if not path.is_absolute():
            raise ValidationError("Path is not aboslute")

        if path.parts[0] in BLACKLISTED_PATHS:
            raise ValidationError(f"Secrets are not allowed to be mounted in {path.parts[0]}")

        return str(path)


class ULIDField(fields.Field):
    """Custom field spec for a ULID field."""

    def _serialize(self, value: Any, attr: str | None, obj: Any, **kwargs: dict) -> str:
        if value is None:
            return ""
        return str(value)

    def _deserialize(self, value: Any, attr: str | None, data: Any, **kwargs: dict) -> str:
        return str(ULID.from_str(value))


class UserSecrets(Schema):
    """User secrets schema."""

    # List of ids of the user's secrets
    user_secret_ids = fields.List(ULIDField(), required=True)
    # Mount path in the main container
    mount_path = PathField(required=True)


@dataclass
class K8sUserSecrets:
    """Class containing the information for the Kubernetes secret that will provide the user secrets."""

    name: str  # Name of the k8s secret containing the user secrets
    user_secret_ids: list[ULID]  # List of user secret ids
    mount_path: str  # Path in the container where to mount the k8s secret
