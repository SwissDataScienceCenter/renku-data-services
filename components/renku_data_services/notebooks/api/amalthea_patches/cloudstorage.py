from typing import Any, Dict, List, TYPE_CHECKING

if TYPE_CHECKING:
    from renku_notebooks.api.classes.server import UserServer
    from renku_notebooks.api.classes.cloud_storage import ICloudStorageRequest


def main(server: "UserServer") -> List[Dict[str, Any]]:
    cloud_storage_patches: List[Dict[str, Any]] = []
    cloud_storage_request: "ICloudStorageRequest"
    for i, cloud_storage_request in enumerate(server.cloudstorage):
        s3mount_name = f"{server.server_name}-ds-{i}"
        cloud_storage_patches.append(
            cloud_storage_request.get_manifest_patch(
                s3mount_name, server._k8s_client.preferred_namespace
            )
        )
    return cloud_storage_patches
