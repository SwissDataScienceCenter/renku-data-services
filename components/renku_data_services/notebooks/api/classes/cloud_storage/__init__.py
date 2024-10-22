"""The protocol for cloud storage."""

from typing import Any, Protocol


class ICloudStorageRequest(Protocol):
    """The abstract class for cloud storage."""

    mount_folder: str
    source_path: str

    def get_manifest_patch(
        self,
        base_name: str,
        namespace: str,
        labels: dict[str, str] | None = None,
        annotations: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """The patches applied to a jupyter server to insert the storage in the session."""
        ...
