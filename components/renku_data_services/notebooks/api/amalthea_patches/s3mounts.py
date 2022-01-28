def main(server):
    s3mount_patches = []
    for i, s3mount in enumerate(server.s3mounts):
        s3mount_name = f"{server.server_name}-ds-{i}"
        s3mount_patches.append(
            s3mount.get_manifest_patches(s3mount_name, server._k8s_namespace)
        )
    return s3mount_patches
