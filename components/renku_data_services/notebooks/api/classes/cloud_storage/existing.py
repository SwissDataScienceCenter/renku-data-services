"""Cloud storage."""

from dataclasses import dataclass
from typing import Any, Self, cast

from renku_data_services.errors import errors
from renku_data_services.notebooks.crs import JupyterServerV1Alpha1


@dataclass
class ExistingCloudStorage:
    """Cloud storage for a session."""

    remote: str
    type: str

    @classmethod
    def from_manifest(cls, manifest: JupyterServerV1Alpha1, storage_class: str = "csi-rclone") -> list[Self]:
        """The patches applied to a jupyter server to insert the storage in the session."""
        if manifest.spec is None:
            raise errors.ProgrammingError(message="Unexpected manifest format")
        output: list[Self] = []
        for patch_collection in manifest.spec.patches:
            for patch in cast(list[dict[str, Any]], patch_collection.patch):
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
