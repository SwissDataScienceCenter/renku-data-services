from dataclasses import dataclass
from typing import Any, Dict, List

from ....config import config


@dataclass
class ExistingCloudStorage:
    bucket: str
    endpoint: str

    @classmethod
    def from_manifest(cls, manifest: Dict[str, Any]) -> List["ExistingCloudStorage"]:
        output: List[ExistingCloudStorage] = []
        endpoint_annotation = (
            config.session_get_endpoint_annotations.renku_annotation_prefix + "endpoint"
        )
        for patch_collection in manifest["spec"]["patches"]:
            for patch in patch_collection["patch"]:
                if patch["op"] == "test":
                    continue
                if not isinstance(patch["value"], dict):
                    continue
                is_persistent_volume = patch["value"].get("kind") == "PersistentVolume"
                driver_is_azure = (
                    patch["value"].get("spec", {}).get("csi", {}).get("driver")
                    == "blob.csi.azure.com"
                )
                has_container_name = (
                    patch["value"]
                    .get("spec", {})
                    .get("csi", {})
                    .get("volumeAttributes", {})
                    .get("containerName")
                )
                if (
                    isinstance(patch["value"], dict)
                    and is_persistent_volume
                    and driver_is_azure
                    and endpoint_annotation
                    in patch["value"].get("metadata", {}).get("annotations", {})
                    and has_container_name
                ):
                    output.append(
                        cls(
                            endpoint=patch["value"]["metadata"]["annotations"][
                                endpoint_annotation
                            ],
                            bucket=patch["value"]["spec"]["csi"]["volumeAttributes"][
                                "containerName"
                            ],
                        )
                    )
                elif patch["value"].get("kind") == "Dataset":
                    output.append(
                        cls(
                            endpoint=patch["value"]["spec"]["local"]["endpoint"],
                            bucket=patch["value"]["spec"]["local"]["bucket"],
                        )
                    )
        return output
