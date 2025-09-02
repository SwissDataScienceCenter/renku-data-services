"""Business logic for connected services."""

from urllib.parse import urlparse

from renku_data_services.connected_services import apispec, models
from renku_data_services.errors import errors


def validate_oauth2_client_patch(patch: apispec.ProviderPatch) -> models.OAuth2ClientPatch:
    """Validate the update to a OAuth2 Client."""
    if patch.image_registry_url is not None and len(patch.image_registry_url) > 0:
        validate_image_registry_url(patch.image_registry_url)
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


def validate_unsaved_oauth2_client(clnt: apispec.ProviderPost) -> models.UnsavedOAuth2Client:
    """Validate the the creation of a new OAuth2 Client."""
    if clnt.image_registry_url is not None:
        validate_image_registry_url(clnt.image_registry_url)
    return models.UnsavedOAuth2Client(
        id=clnt.id,
        kind=clnt.kind,
        app_slug=clnt.app_slug or "",
        client_id=clnt.client_id,
        client_secret=clnt.client_secret,
        display_name=clnt.display_name,
        scope=clnt.scope,
        url=clnt.url,
        use_pkce=clnt.use_pkce or False,
        image_registry_url=clnt.image_registry_url,
    )


def validate_image_registry_url(url: str) -> None:
    """Validate an image registry url."""
    parsed = urlparse(url)
    if not parsed.netloc:
        raise errors.ValidationError(
            message=f"The host for the image registry url {url} is not valid, expected a non-empty value.",
            quiet=True,
        )
    accepted_schemes = ["https"]
    if parsed.scheme not in accepted_schemes:
        raise errors.ValidationError(
            message=f"The scheme for the image registry url {url} is not valid, expected one of {accepted_schemes}",
            quiet=True,
        )
