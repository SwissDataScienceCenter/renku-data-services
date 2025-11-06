"""Utilities for OCI images."""

from typing import TYPE_CHECKING

import httpx

from renku_data_services import errors
from renku_data_services.app_config import logging
from renku_data_services.notebooks.oci.image_config import ImageConfig
from renku_data_services.notebooks.oci.image_index import ImageIndex, Platform
from renku_data_services.notebooks.oci.image_manifest import ImageManifest
from renku_data_services.notebooks.oci.models import ManifestMediaTypes

if TYPE_CHECKING:
    from renku_data_services.notebooks.api.classes.image import Image, ImageRepoDockerAPI

logger = logging.getLogger(__name__)


async def get_image_platforms(
    manifest_response: httpx.Response, image: "Image", reg_api: "ImageRepoDockerAPI"
) -> list[Platform] | None:
    """Returns the list of platforms supported by the image manifest."""
    try:
        parsed = parse_manifest_response(manifest_response)
    except Exception as err:
        logger.warning(f"Error parsing image manifest: {err}")
        return None

    if isinstance(parsed, ImageIndex):
        platforms: list[Platform] = []
        for manifest in parsed.manifests:
            # Ignore manifests without a platform
            if (
                manifest.platform is None
                or manifest.platform.os == "unknown"
                or manifest.platform.architecture == "unknown"
            ):
                continue
            platforms.append(manifest.platform)
        return platforms

    try:
        config_response = await reg_api.get_image_config_from_digest(image=image, config_digest=parsed.config.digest)
    except Exception as err:
        logger.warning(f"Error getting image config: {err}")
        return None

    try:
        parsed_config = parse_config_response(config_response)
    except Exception as err:
        logger.warning(f"Error parsing image config: {err}")
        return None

    platform = Platform.model_validate(
        {
            "architecture": parsed_config.architecture,
            "os": parsed_config.os,
            "os.feature": parsed_config.os_features,
            "os.version": parsed_config.os_version,
            "variant": parsed_config.variant,
        },
    )
    return [platform]


def parse_manifest_response(response: httpx.Response) -> ImageIndex | ImageManifest:
    """Parse a manifest response."""

    content_type = response.headers.get("Content-Type")
    if content_type not in {
        ManifestMediaTypes.docker_list_v2,
        ManifestMediaTypes.docker_manifest_v2,
        ManifestMediaTypes.oci_index_v1,
        ManifestMediaTypes.oci_manifest_v1,
    }:
        raise errors.ValidationError(message=f"Unexpected content type {content_type}.")

    if content_type in {ManifestMediaTypes.docker_list_v2, ManifestMediaTypes.oci_index_v1}:
        return ImageIndex.model_validate_json(response.content)
    else:
        return ImageManifest.model_validate_json(response.content)


def parse_config_response(response: httpx.Response) -> ImageConfig:
    """Parse a config response."""

    content_type = response.headers.get("Content-Type")
    if content_type not in {
        ManifestMediaTypes.docker_config_v2,
        ManifestMediaTypes.oci_config_v1,
    }:
        raise errors.ValidationError(message=f"Unexpected content type {content_type}.")

    return ImageConfig.model_validate_json(response.content)
