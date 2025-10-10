"""Business logic for the platform configuration."""

import os
import re
from urllib.parse import ParseResult, urlparse

from renku_data_services import errors
from renku_data_services.platform import apispec, models

v2_project_pattern = re.compile(r"^/p/[0-7][0-9A-HJKMNP-TV-Z]{25}$")


def validate_platform_config_patch(patch: apispec.PlatformConfigPatch) -> models.PlatformConfigPatch:
    """Validate the update to the platform configuration."""
    return models.PlatformConfigPatch(incident_banner=patch.incident_banner)


def _ensure_no_extras(parsed: ParseResult, position: str) -> None:
    """Ensure that the parsed URL has no extra components."""
    if parsed.params or parsed.query or parsed.fragment:
        raise errors.ValidationError(message=f"The {position} URL must not include parameters, a query, or a fragment.")
    canonical_path = os.path.normpath(parsed.path)
    if parsed.path != canonical_path:
        raise errors.ValidationError(message=f"The {position} URL path is not canonical.")


def _validate_source_gitlab_url(parsed: ParseResult) -> str:
    """Validate the GitLab URL."""
    if parsed.scheme != "https":
        raise errors.ValidationError(message="The source URL must use HTTPS.")
    if parsed.netloc != "gitlab.renkulab.io":
        raise errors.ValidationError(message="The source URL host must be gitlab.renkulab.io.")
    return parsed.geturl()


def _validate_source_v1_url(parsed: ParseResult) -> str:
    """Validate the source V1 URL."""
    if parsed.scheme:
        raise errors.ValidationError(message="The source URL should not include a scheme.")
    if parsed.netloc:
        raise errors.ValidationError(message="The source URL should not include a host.")
    if not parsed.path.startswith("/projects/"):
        raise errors.ValidationError(message="The source URL must start with /projects/.")
    return parsed.geturl()


def _validate_target_external_url(parsed: ParseResult) -> str:
    """Validate the external target URL."""
    if parsed.scheme != "https":
        raise errors.ValidationError(message="The target URL must use HTTPS.")
    return parsed.geturl()


def _validate_target_v2_project_url(parsed: ParseResult) -> str:
    """Validate the target V2 project URL."""
    if parsed.scheme:
        raise errors.ValidationError(message="The target URL should not include a scheme.")
    if parsed.netloc:
        raise errors.ValidationError(message="The target URL should not include a host.")
    if not v2_project_pattern.match(parsed.path):
        raise errors.ValidationError(message="The target URL path must match the pattern /p/ULID.")
    return parsed.geturl()


def validate_source_url(url: str) -> str:
    """Validate the source URL."""
    parsed = urlparse(url)
    _ensure_no_extras(parsed, "source")
    if parsed.scheme:
        return _validate_source_gitlab_url(parsed)
    return _validate_source_v1_url(parsed)


def validate_target_url(url: str) -> str:
    """Validate the target URL."""
    parsed = urlparse(url)
    _ensure_no_extras(parsed, "target")
    if parsed.scheme or parsed.netloc:
        return _validate_target_external_url(parsed)
    return _validate_target_v2_project_url(parsed)


def validate_url_redirect_patch(source_url: str, patch: apispec.UrlRedirectPlanPatch) -> models.UrlRedirectUpdateConfig:
    """Validate the update of a URL redirect."""
    return models.UrlRedirectUpdateConfig(
        source_url=validate_source_url(source_url),
        target_url=validate_target_url(patch.target_url) if patch.target_url is not None else None,
    )


def validate_url_redirect_post(post: apispec.UrlRedirectPlanPost) -> models.UnsavedUrlRedirectConfig:
    """Validate the creation of a URL redirect."""
    return models.UnsavedUrlRedirectConfig(
        source_url=validate_source_url(post.source_url),
        target_url=validate_target_url(post.target_url),
    )
