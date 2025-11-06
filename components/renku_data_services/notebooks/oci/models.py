"""Constants related to OCI images."""

from dataclasses import dataclass
from enum import StrEnum


class ManifestMediaTypes(StrEnum):
    """The content types related to OCI image manifests."""

    docker_config_v2 = "application/vnd.docker.container.image.v1+json"
    docker_manifest_v2 = "application/vnd.docker.distribution.manifest.v2+json"
    docker_list_v2 = "application/vnd.docker.distribution.manifest.list.v2+json"
    oci_config_v1 = "application/vnd.oci.image.config.v1+json"
    oci_manifest_v1 = "application/vnd.oci.image.manifest.v1+json"
    oci_index_v1 = "application/vnd.oci.image.index.v1+json"


@dataclass(frozen=True, eq=True, kw_only=True, order=True)
class Platform:
    """Represents a runtime platform."""

    architecture: str
    os: str
    variant: str | None = None
    os_version: str | None = None
    os_features: list[str] | None = None
