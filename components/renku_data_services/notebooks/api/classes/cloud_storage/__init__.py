"""The protocol for cloud storage."""

from typing import Any, Protocol


class ICloudStorageRequest(Protocol):
    """The abstract class for cloud storage."""

    exists: bool
    mount_folder: str
    source_folder: str
    bucket: str

    def get_manifest_patch(
        self,
        base_name: str,
        namespace: str,
        labels: dict[str, str] = {},
        annotations: dict[str, str] = {},
    ) -> list[dict[str, Any]]:
        """The patches applied to a jupyter server to insert the storage in the session."""
        ...
