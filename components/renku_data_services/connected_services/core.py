"""Business logic for connected services."""

from urllib.parse import urlparse
from renku_data_services.connected_services import apispec, models
from renku_data_services.errors import errors


def validate_oauth2_client_patch(patch: apispec.ProviderPatch) -> models.OAuth2ClientPatch:
    """Validate the update to a OAuth2 Client."""
    return models.OAuth2ClientPatch(
        kind=patch.kind,
        app_slug=patch.app_slug,
        client_id=patch.client_id,
        client_secret=patch.client_secret,
        display_name=patch.display_name,
        scope=patch.scope,
        url=patch.url,
        use_pkce=patch.use_pkce,
        image_registry_url=patch.image_registry_url,
    )


def validate_image_registry_url(url: str) -> None:
    """Validate an image registry url."""
    parsed = urlparse(url)
    if not parsed.netloc:
        raise errors.ValidationError(
            message=f"The host for the image registry url {url} is not valid, expected a non-empty value.",
            quiet=True,
        )
    accepted_schemes = ["http", "https"]
    if parsed.scheme not in accepted_schemes:
        raise errors.ValidationError(
            message=f"The scheme for the image registry url {url} is not valid, expected one of {accepted_schemes}",
            quiet=True,
        )
