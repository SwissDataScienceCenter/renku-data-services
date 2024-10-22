"""Various utilities for patching sessions."""

from typing import Any, cast

from kubernetes import client

from renku_data_services.notebooks.config import NotebooksConfig


def get_certificates_volume_mounts(
    config: NotebooksConfig,
    etc_certs: bool = True,
    custom_certs: bool = True,
    read_only_etc_certs: bool = False,
) -> list[dict[str, Any]]:
    """The list of volume mounts for custom certificates."""
    volume_mounts = []
    etc_ssl_certs = client.V1VolumeMount(
        name="etc-ssl-certs",
        mount_path="/etc/ssl/certs/",
        read_only=read_only_etc_certs,
    )
    custom_ca_certs = client.V1VolumeMount(
        name="custom-ca-certs",
        mount_path=config.sessions.ca_certs.path,
        read_only=True,
    )
    if etc_certs:
        volume_mounts.append(etc_ssl_certs)
    if custom_certs:
        volume_mounts.append(custom_ca_certs)
    return cast(list[dict[str, Any]], client.ApiClient().sanitize_for_serialization(volume_mounts))
