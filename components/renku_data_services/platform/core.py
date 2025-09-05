"""Business logic for the platform configuration."""

from renku_data_services.platform import apispec, models


def validate_platform_config_patch(patch: apispec.PlatformConfigPatch) -> models.PlatformConfigPatch:
    """Validate the update to the platform configuration."""
    return models.PlatformConfigPatch(incident_banner=patch.incident_banner)


def validate_url_redirect_post(post: apispec.UrlRedirectPlanPost) -> models.UnsavedUrlRedirectConfig:
    """Validate the creation of a URL redirect."""
    return models.UnsavedUrlRedirectConfig(
        source_url=post.source_url,
        target_url=post.target_url,
    )
