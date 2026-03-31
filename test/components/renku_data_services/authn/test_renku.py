import jwt

from renku_data_services.authn.renku import RenkuSelfAuthenticator
from renku_data_services.base_models import AuthenticatedAPIUser


def test_make_user_claims() -> None:
    user = AuthenticatedAPIUser(
        id="some-user-id",
        is_admin=False,
        access_token="some-access-token",
        full_name="Jane Doe",
        first_name="Jane",
        last_name="Doe",
        email="jane.doe@example.org",
        roles=[],
    )

    user_claims = RenkuSelfAuthenticator._make_user_claims(user=user)

    expected_claims = {
        "sub": "some-user-id",
        "email": "jane.doe@example.org",
        "name": "Jane Doe",
        "given_name": "Jane",
        "family_name": "Doe",
    }
    assert user_claims == expected_claims


def test_mint_token() -> None:
    secret_key = "hello"
    user = AuthenticatedAPIUser(
        id="some-user-id",
        is_admin=False,
        access_token="some-access-token",
        full_name="Jane Doe",
        first_name="Jane",
        last_name="Doe",
        email="jane.doe@example.org",
        roles=[],
    )

    payload = RenkuSelfAuthenticator._make_payload(user=user)
    strict_jwt = jwt.PyJWT({"enforce_minimum_key_length": True})

    encoded = strict_jwt.encode(payload, key=secret_key, algorithm="HS512")
    assert encoded == ""


def test_key() -> None:
    secret_key = "hello"
    alg = jwt.get_algorithm_by_name("HS512")
    jwk = alg.to_jwk(key_obj=secret_key)
    assert jwk is None
