"""Cloud storage."""

from dataclasses import dataclass
from typing import Any, Self


@dataclass
class ExistingCloudStorage:
    """Cloud storage for a session."""

    remote: str
    type: str

    @classmethod
    def from_manifest(cls, manifest: dict[str, Any], storage_class: str = "csi-rclone") -> list[Self]:
        """The patches applied to a jupyter server to insert the storage in the session."""
        output: list[Self] = []
        for patch_collection in manifest["spec"]["patches"]:
            for patch in patch_collection["patch"]:
                if patch["op"] == "test":
                    continue
                if not isinstance(patch["value"], dict):
                    continue
                is_persistent_volume = patch["value"].get("kind") == "PersistentVolume"
                is_rclone = patch["value"].get("spec", {}).get("csi", {}).get("driver", "") == storage_class
                if isinstance(patch["value"], dict) and is_persistent_volume and is_rclone:
                    configData = patch["value"]["spec"]["csi"]["volumeAttributes"]["configData"].splitlines()
                    _, storage_type = next(
                        (line.strip().split("=") for line in configData if line.startswith("type")),
                        (None, "Unknown"),
                    )
                    output.append(
                        cls(
                            remote=patch["value"]["spec"]["csi"]["volumeAttributes"]["remote"],
                            type=storage_type.strip(),
                        )
                    )
        return output
