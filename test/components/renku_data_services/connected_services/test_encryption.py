"""Tests for the encryption in connected services."""

import pytest
from sqlalchemy import select

from renku_data_services.app_config import Config
from renku_data_services.base_models import APIUser
from renku_data_services.connected_services import apispec
from renku_data_services.connected_services import orm as schemas
from renku_data_services.migrations.core import run_migrations_for_app
from renku_data_services.utils.cryptography import decrypt_string


def test_token_encryption(
    app_config: Config,
    db_instance,
    authz_instance,
) -> None:
    run_migrations_for_app("common")
    connected_services_repo = app_config.connected_services_repo
    token = dict(access_token="ACCESS TOKEN", refresh_token="REFRESH TOKEN", expires_at=12345)  # nosec
    user_id = "USER-1"

    encrypted_token = connected_services_repo._encrypt_token_set(token=token, user_id=user_id)

    assert encrypted_token is not None
    assert encrypted_token.access_token != token["access_token"]
    assert encrypted_token.refresh_token != token["refresh_token"]
    assert encrypted_token.expires_at == token["expires_at"]

    decrypted_token = connected_services_repo._decrypt_token_set(token=encrypted_token, user_id=user_id)

    assert decrypted_token is not None
    assert decrypted_token.access_token == token["access_token"]
    assert decrypted_token.refresh_token == token["refresh_token"]
    assert decrypted_token.expires_at == token["expires_at"]


@pytest.mark.asyncio
async def test_client_secret_encryption(app_config: Config, db_instance, authz_instance, admin_user: APIUser) -> None:
    run_migrations_for_app("common")
    connected_services_repo = app_config.connected_services_repo
    new_client = apispec.ProviderPost(
        id="provider",
        kind=apispec.ProviderKind.gitlab,
        client_id="CLIENT_ID",
        client_secret="CLIENT_SECRET",  # nosec
        display_name="My Provider",
        scope="api",
        url="https://example.org",
        use_pkce=False,
    )

    client = await connected_services_repo.insert_oauth2_client(user=admin_user, new_client=new_client)

    assert client is not None
    assert client.id == new_client.id
    assert client.client_secret == "redacted"  # nosec

    async with connected_services_repo.session_maker() as session:
        result = await session.scalars(select(schemas.OAuth2ClientORM).where(schemas.OAuth2ClientORM.id == client.id))
        stored_client = result.one_or_none()

    assert stored_client is not None
    assert stored_client.client_secret != "CLIENT_SECRET"  # nosec

    decrypted_secret = decrypt_string(
        connected_services_repo.encryption_key, admin_user.id, stored_client.client_secret
    )

    assert decrypted_secret == "CLIENT_SECRET"  # nosec
