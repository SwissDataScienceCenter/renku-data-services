"""Tests for the encryption in connected services."""

import json
from uuid import uuid4

import pytest
from sqlalchemy import select

from renku_data_services.app_config import Config
from renku_data_services.base_models import APIUser
from renku_data_services.connected_services import apispec
from renku_data_services.connected_services import orm as schemas
from renku_data_services.utils.cryptography import decrypt_string


@pytest.fixture
def admin_api_user() -> APIUser:
    id = str(uuid4())
    full_name = "Some Admin"
    first_name = "Some"
    last_name = "Admin"
    email = "some-admin@example.org"
    is_admin = True
    return APIUser(
        is_admin=is_admin,
        id=id,
        full_name=full_name,
        # The dummy authentication client in the tests will parse the access token to create
        # the same APIUser as this when it receives this json-formatted access token
        access_token=json.dumps(
            {
                "id": id,
                "first_name": first_name,
                "last_name": last_name,
                "email": email,
                "is_admin": is_admin,
                "full_name": full_name,
            }
        ),
    )


def test_token_encryption(app_config: Config):
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
async def test_client_secret_encryption(app_config: Config, admin_api_user: APIUser):
    connected_services_repo = app_config.connected_services_repo
    new_client = apispec.ProviderPost(
        id="provider",
        kind=apispec.ProviderKind.gitlab,
        client_id="CLIENT_ID",
        client_secret="CLIENT_SECRET",  # nosec
        display_name="My Provider",
        scope="api",
        url="https://example.org",
    )

    client = await connected_services_repo.insert_oauth2_client(user=admin_api_user, new_client=new_client)

    assert client is not None
    assert client.id == new_client.id
    assert client.client_secret == "redacted"  # nosec

    async with connected_services_repo.session_maker() as session:
        result = await session.scalars(select(schemas.OAuth2ClientORM).where(schemas.OAuth2ClientORM.id == client.id))
        stored_client = result.one_or_none()

    assert stored_client is not None
    assert stored_client.client_secret != "CLIENT_SECRET"  # nosec

    decrypted_secret = decrypt_string(
        connected_services_repo.encryption_key, admin_api_user.id, stored_client.client_secret
    )

    assert decrypted_secret == "CLIENT_SECRET"  # nosec
