from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import jwt
import pytest
import pytest_asyncio
from sanic import Request, Sanic
from sanic.response import JSONResponse, json
from ulid import ULID

from renku_data_services.app_config.config import InternalAuthenticationConfig
from renku_data_services.authn.renku import RenkuSelfAuthenticator, RenkuSelfTokenMint
from renku_data_services.base_models import AuthenticatedAPIUser
from test.utils import SanicReusableASGITestClient

if TYPE_CHECKING:
    from pytest import MonkeyPatch


@pytest.fixture
def local_test_user() -> AuthenticatedAPIUser:
    return AuthenticatedAPIUser(
        id="some-user-id",
        is_admin=False,
        access_token="some-access-token",
        full_name="Jane Doe",
        first_name="Jane",
        last_name="Doe",
        email="jane.doe@example.org",
        roles=[],
    )


def test_make_user_claims(local_test_user: AuthenticatedAPIUser) -> None:
    user_claims = RenkuSelfTokenMint._make_user_claims(user=local_test_user)

    expected_claims = {
        "sub": "some-user-id",
        "email": "jane.doe@example.org",
        "name": "Jane Doe",
        "given_name": "Jane",
        "family_name": "Doe",
    }
    assert user_claims == expected_claims


@pytest.fixture
async def internal_token_mint(monkeypatch: "MonkeyPatch") -> RenkuSelfTokenMint:
    monkeypatch.setenv("DUMMY_STORES", "true")
    internal_authn_config = InternalAuthenticationConfig.from_env()
    return RenkuSelfTokenMint.from_config(config=internal_authn_config)


def test_make_payload(local_test_user: AuthenticatedAPIUser, internal_token_mint: RenkuSelfTokenMint) -> None:
    expires_in = timedelta(minutes=10)

    payload = internal_token_mint._make_payload(
        user=local_test_user, token_type="Bearer", scope="test_scope", expires_in=expires_in
    )

    expected_keys = {
        "exp",
        "iat",
        "nbf",
        "iss",
        "aud",
        "jti",
        "typ",
        "scope",
        "sub",
        "email",
        "name",
        "given_name",
        "family_name",
    }
    assert set(payload.keys()) == expected_keys

    assert isinstance(payload.get("exp"), int)
    assert isinstance(payload.get("iat"), int)
    assert isinstance(payload.get("nbf"), int)
    now = datetime.now(UTC)
    iat_diff_now = datetime.fromtimestamp(int(payload["iat"]), UTC) - now
    assert abs(iat_diff_now) < timedelta(seconds=1), "issued-at is not now"
    result_expires_in = timedelta(seconds=int(payload["exp"]) - int(payload["iat"]))
    assert result_expires_in == expires_in
    assert int(payload["nbf"]) <= int(payload["iat"]), "not-before is after issued-at"
    assert payload.get("iss") == "renku-self"
    assert payload.get("aud") == "renku-self"
    assert isinstance(payload.get("jti"), str)
    ULID.from_str(payload["jti"])
    assert payload.get("typ") == "Bearer"

    assert payload.get("scope") == "test_scope"

    assert payload.get("sub") == "some-user-id"
    assert payload.get("email") == "jane.doe@example.org"
    assert payload.get("name") == "Jane Doe"
    assert payload.get("given_name") == "Jane"
    assert payload.get("family_name") == "Doe"


def test_create_access_token(local_test_user: AuthenticatedAPIUser, internal_token_mint: RenkuSelfTokenMint) -> None:
    token = internal_token_mint.create_access_token(user=local_test_user, scope="test_scope")

    strict_jwt = jwt.PyJWT({"enforce_minimum_key_length": True})
    parsed_token = strict_jwt.decode(
        token,
        key=internal_token_mint.secret_key,
        algorithms=[internal_token_mint.algorithm],
        issuer=internal_token_mint.issuer,
        audience=internal_token_mint.audience,
    )

    assert parsed_token.get("typ") == "Bearer"
    assert parsed_token.get("aud") == "renku-self"
    assert parsed_token.get("sub") == "some-user-id"
    assert parsed_token.get("scope") == "test_scope"


def test_create_refresh_token(local_test_user: AuthenticatedAPIUser, internal_token_mint: RenkuSelfTokenMint) -> None:
    token = internal_token_mint.create_refresh_token(user=local_test_user, scope="test_scope")

    strict_jwt = jwt.PyJWT({"enforce_minimum_key_length": True})
    parsed_token = strict_jwt.decode(
        token,
        key=internal_token_mint.secret_key,
        algorithms=[internal_token_mint.algorithm],
        issuer=internal_token_mint.issuer,
        audience=internal_token_mint.audience,
    )

    assert parsed_token.get("typ") == "Refresh"
    assert parsed_token.get("aud") == "renku-self"
    assert parsed_token.get("sub") == "some-user-id"
    assert parsed_token.get("scope") == "test_scope"


@pytest_asyncio.fixture(scope="session")
async def monkeysession():
    mpatch = pytest.MonkeyPatch()
    with mpatch.context():
        yield mpatch


@pytest_asyncio.fixture(scope="session")
async def shared_internal_authn_config(monkeysession: "MonkeyPatch") -> InternalAuthenticationConfig:
    monkeysession.setenv("DUMMY_STORES", "true")
    return InternalAuthenticationConfig.from_env()


@pytest_asyncio.fixture(scope="session")
async def shared_internal_token_mint(shared_internal_authn_config: InternalAuthenticationConfig) -> RenkuSelfTokenMint:
    return RenkuSelfTokenMint.from_config(config=shared_internal_authn_config)


@pytest_asyncio.fixture(scope="session")
async def shared_sanic_client(
    shared_internal_authn_config: InternalAuthenticationConfig,
) -> SanicReusableASGITestClient:
    internal_authenticator = RenkuSelfAuthenticator.from_config(config=shared_internal_authn_config)
    app = Sanic("test_authn_renku")

    # Test route with authenticator
    async def test_handler(request: Request) -> JSONResponse:
        access_token = request.headers.get(internal_authenticator.token_field)
        user = await internal_authenticator.authenticate(access_token=access_token or "", request=request)
        result = {
            "is_authenticated": user.is_authenticated,
            "id": user.id,
        }
        if user.email:
            result["email"] = user.email
        return json(result)

    app.add_route(test_handler, "/test", methods=["GET"], name="test_handler")

    async with SanicReusableASGITestClient(app) as client:
        yield client


@pytest.mark.asyncio
async def test_authenticator_anonymous(shared_sanic_client: SanicReusableASGITestClient) -> None:
    headers = {"Renku-Auth-Anon-Id": "anon-my-user-id"}
    _, response = await shared_sanic_client.get("/test", headers=headers)

    assert response.status_code == 200, response.text
    assert isinstance(response.json, dict)
    assert isinstance(response.json.get("is_authenticated"), bool)
    assert not response.json["is_authenticated"], "user should not be authenticated"
    assert response.json.get("id") == "anon-my-user-id"


@pytest.mark.asyncio
async def test_authenticator_valid_access_token(
    local_test_user: AuthenticatedAPIUser,
    shared_sanic_client: SanicReusableASGITestClient,
    shared_internal_token_mint: RenkuSelfTokenMint,
) -> None:
    access_token = shared_internal_token_mint.create_access_token(user=local_test_user)

    headers = {"Authorization": f"Bearer {access_token}"}
    _, response = await shared_sanic_client.get("/test", headers=headers)

    assert response.status_code == 200, response.text
    assert isinstance(response.json, dict)
    assert isinstance(response.json.get("is_authenticated"), bool)
    assert response.json["is_authenticated"], "user should be authenticated"
    assert response.json.get("id") == "some-user-id"
    assert response.json.get("email") == "jane.doe@example.org"
