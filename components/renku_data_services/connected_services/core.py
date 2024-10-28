"""Business logic for connected services."""

from renku_data_services.connected_services import apispec, models


def validate_oauth2_client_patch(patch: apispec.ProviderPatch) -> models.OAuth2ClientPatch:
    """Validate the update to a OAuth2 Client."""
    return models.OAuth2ClientPatch(
        kind=patch.kind,
        client_id=patch.client_id,
        client_secret=patch.client_secret,
        display_name=patch.display_name,
        scope=patch.scope,
        url=patch.url,
        use_pkce=patch.use_pkce,
    )
