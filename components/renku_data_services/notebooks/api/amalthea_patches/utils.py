"""Various utilities for patching sessions."""

from typing import Any, cast

from kubernetes import client

from renku_data_services.k8s.models import sanitizer
from renku_data_services.notebooks.config import NotebooksConfig
from renku_data_services.notebooks.crs import ExtraVolumeMount


def get_certificates_volume_mounts_unserialized(
    config: NotebooksConfig,
    etc_certs: bool = True,
    custom_certs: bool = True,
    read_only_etc_certs: bool = False,
) -> list[ExtraVolumeMount]:
    """The list of volume mounts for custom certificates."""
    volume_mounts = []
    etc_ssl_certs = ExtraVolumeMount(
        name="etc-ssl-certs",
        mountPath="/etc/ssl/certs/",
        readOnly=read_only_etc_certs,
    )
    custom_ca_certs = ExtraVolumeMount(
        name="custom-ca-certs",
        mountPath=config.sessions.ca_certs.path,
        readOnly=True,
    )
    if etc_certs:
        volume_mounts.append(etc_ssl_certs)
    if custom_certs:
        volume_mounts.append(custom_ca_certs)
    return volume_mounts


def __convert_extra_volume_mounts(input: list[ExtraVolumeMount]) -> list[client.V1VolumeMount]:
    """Convert between different volume mount types."""
    return [
        client.V1VolumeMount(
            mount_path=vol.mountPath,
            mount_propagation=vol.mountPropagation,
            name=vol.name,
            read_only=vol.readOnly,
            recursive_read_only=vol.recursiveReadOnly,
            sub_path=vol.subPath,
            sub_path_expr=vol.subPathExpr,
        )
        for vol in input
    ]


def get_certificates_volume_mounts(
    config: NotebooksConfig,
    etc_certs: bool = True,
    custom_certs: bool = True,
    read_only_etc_certs: bool = False,
) -> list[dict[str, Any]]:
    """The list of volume mounts for custom certificates."""
    vol_mounts = get_certificates_volume_mounts_unserialized(config, etc_certs, custom_certs, read_only_etc_certs)
    vol_mounts_ser = __convert_extra_volume_mounts(vol_mounts)
    return cast(list[dict[str, Any]], sanitizer(vol_mounts_ser))
