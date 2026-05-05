"""Business logic for connected services."""

import math
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import jwt
from ulid import ULID

from renku_data_services import base_models, errors
from renku_data_services.app_config import logging
from renku_data_services.authn.api.core import ScopeVerifier
from renku_data_services.authn.renku import RenkuSelfAuthenticator, RenkuSelfTokenMint
from renku_data_services.connected_services import apispec, models
from renku_data_services.connected_services.oauth_http import (
    OAuthHttpClientFactory,
)

logger = logging.getLogger(__name__)


def validate_oauth2_client_patch(patch: apispec.ProviderPatch) -> models.OAuth2ClientPatch:
    """Validate the update to a OAuth2 Client."""
    if patch.image_registry_url:
        validate_image_registry_url(patch.image_registry_url)
    kind = models.ProviderKind(patch.kind.value) if patch.kind else None
    if kind == models.ProviderKind.generic_oidc:
        if not patch.oidc_issuer_url:
            raise errors.ValidationError(
                message=f"The field 'oidc_issuer_url' is required when kind is set to {models.ProviderKind.generic_oidc.value}.",  # noqa E501
                quiet=True,
            )
        validate_oidc_issuer_url(patch.oidc_issuer_url)
    return models.OAuth2ClientPatch(
        kind=kind,
        app_slug=patch.app_slug,
        client_id=patch.client_id,
        client_secret=patch.client_secret,
        display_name=patch.display_name,
        scope=patch.scope,
        url=patch.url,
        use_pkce=patch.use_pkce,
        image_registry_url=patch.image_registry_url,
        oidc_issuer_url=patch.oidc_issuer_url,
    )


def validate_unsaved_oauth2_client(clnt: apispec.ProviderPost) -> models.UnsavedOAuth2Client:
    """Validate the creation of a new OAuth2 Client."""
    if clnt.image_registry_url is not None:
        validate_image_registry_url(clnt.image_registry_url)
    kind = models.ProviderKind(clnt.kind.value)
    if clnt.oidc_issuer_url and kind != models.ProviderKind.generic_oidc:
        raise errors.ValidationError(
            message=f"The field 'oidc_issuer_url' can only be set when kind is set to {models.ProviderKind.generic_oidc.value}.",  # noqa E501
            quiet=True,
        )
    if kind == models.ProviderKind.generic_oidc:
        if not clnt.oidc_issuer_url:
            raise errors.ValidationError(
                message=f"The field 'oidc_issuer_url' is required when kind is set to {models.ProviderKind.generic_oidc.value}.",  # noqa E501
                quiet=True,
            )
        validate_oidc_issuer_url(clnt.oidc_issuer_url)
    return models.UnsavedOAuth2Client(
        id=clnt.id,
        kind=kind,
        app_slug=clnt.app_slug or "",
        client_id=clnt.client_id,
        client_secret=clnt.client_secret,
        display_name=clnt.display_name,
        scope=clnt.scope,
        url=clnt.url,
        use_pkce=clnt.use_pkce or False,
        image_registry_url=clnt.image_registry_url,
        oidc_issuer_url=clnt.oidc_issuer_url,
    )


def validate_image_registry_url(url: str) -> None:
    """Validate an image registry url."""
    parsed = urlparse(url)
    if not parsed.netloc:
        raise errors.ValidationError(
            message=f"The image registry url {url} is not valid, expected a valid url starting with the scheme.",
            quiet=True,
        )
    accepted_schemes = ["https"]
    if parsed.scheme not in accepted_schemes:
        raise errors.ValidationError(
            message=f"The scheme for the image registry url {url} is not valid, expected one of {accepted_schemes}",
            quiet=True,
        )


def validate_oidc_issuer_url(url: str) -> None:
    """Validate an OpenID Connect Issuer URL."""
    parsed = urlparse(url)
    if not parsed.netloc:
        raise errors.ValidationError(
            message=f"The host for the 'oidc_issuer_url' {url} is not valid, expected a non-empty value.",
            quiet=True,
        )
    accepted_schemes = ["https"]
    if parsed.scheme not in accepted_schemes:
        raise errors.ValidationError(
            message=f"The scheme for the 'oidc_issuer_url' {url} is not valid, expected one of {accepted_schemes}",
            quiet=True,
        )


async def handle_oauth2_token_refresh(
    body: apispec.PostTokenRequest,
    connection_id: ULID,
    oauth_client_factory: OAuthHttpClientFactory,
    internal_authenticator: RenkuSelfAuthenticator,
    internal_token_mint: RenkuSelfTokenMint,
    internal_scope_verifier: ScopeVerifier,
) -> dict[str, str | int]:
    """OAuth 2.0 token endpoint to support applications running in sessions.

    Details:
        1. Check that `body.refresh_token` is a valid internal refresh token
        2. Send back the refreshed OAuth 2.0 access token and a new internal refresh token
    """
    parsed_renku_refresh_token = await internal_authenticator.verify_refresh_token(refresh_token=body.refresh_token)
    if parsed_renku_refresh_token is None:
        raise errors.UnauthorizedError(message="You have to be authenticated to perform this operation.")
    user = base_models.AuthenticatedAPIUser(
        is_admin=False,
        id=parsed_renku_refresh_token["sub"],
        access_token="",  # nosec B106
        full_name=parsed_renku_refresh_token.get("name"),
        first_name=parsed_renku_refresh_token.get("given_name"),
        last_name=parsed_renku_refresh_token.get("family_name"),
        email=parsed_renku_refresh_token["email"],
        access_token_expires_at=None,
        roles=[],
    )

    # Verify the scope claim
    scope = str(parsed_renku_refresh_token.get("scope", ""))
    await internal_scope_verifier.verify_scope(user=user, scope=scope)

    client = await oauth_client_factory.for_user_connection_raise(user, connection_id)
    oauth_token = await client.get_token()
    access_token = oauth_token.access_token
    if access_token is None:
        raise errors.ProgrammingError(message="Unexpected error: access token not present.")
    expires_in_td = internal_token_mint.long_refresh_token_expiration
    new_renku_refresh_token = internal_token_mint.create_refresh_token(
        user=user, scope=scope, refresh_expires_in=expires_in_td
    )
    result: dict[str, str | int] = {
        "access_token": access_token,
        "token_type": str(oauth_token.get("token_type")) or "Bearer",
        "refresh_token": new_renku_refresh_token,
    }
    if oauth_token.get("scope"):
        result["scope"] = oauth_token["scope"]
    # NOTE: Set "expires_in" according to whichever of the OAuth 2.0 access token or the Renku refresh
    # token expires first.
    try:
        refresh_decoded: dict[str, Any] = jwt.decode(new_renku_refresh_token, options={"verify_signature": False})
        refresh_exp: int | None = refresh_decoded.get("exp")
        if refresh_exp is not None and refresh_exp > 0:
            exp = datetime.fromtimestamp(refresh_exp, UTC)
            expires_in = exp - datetime.now(UTC)
            result["expires_in"] = math.floor(expires_in.total_seconds())
    except Exception as err:
        logger.error(f"Could not parse Renku refresh token; cannot determine its expiration: {err.__class__}.")
    if oauth_token.expires_at:
        exp = datetime.fromtimestamp(oauth_token.expires_at, UTC)
        expires_in = exp - datetime.now(UTC)
        result_expires_in = result.get("expires_in")
        if isinstance(result_expires_in, int) and result_expires_in > 0:
            result["expires_in"] = min(result_expires_in, math.floor(expires_in.total_seconds()))
        else:
            result["expires_in"] = math.floor(expires_in.total_seconds())

    return result
