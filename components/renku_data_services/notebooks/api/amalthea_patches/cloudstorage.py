from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from renku_notebooks.api.classes.server import UserServer


def main(server: "UserServer"):
    s3mount_patches = []
    for i, s3mount in enumerate(server.cloudstorage):
        s3mount_name = f"{server.server_name}-ds-{i}"
        s3mount_patches.append(
            s3mount.get_manifest_patches(
                s3mount_name, server._k8s_client.preferred_namespace
            )
        )
    return s3mount_patches
